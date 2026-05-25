from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List
import math
import re

from src.engine.agents import run_fallback_agent, run_risk_agent, run_technical_agent
import logging
from src.engine.judge import run_consensus_judge


def _tokenize(text: str) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(token) > 1]


def _score_block(spec_text: str, block_text: str) -> float:
    spec_tokens = _tokenize(spec_text)
    block_tokens = _tokenize(block_text)
    if not spec_tokens or not block_tokens:
        return 0.0
    spec_counts = Counter(spec_tokens)
    block_counts = Counter(block_tokens)
    common = set(spec_counts) & set(block_counts)
    if not common:
        return 0.0
    score = 0.0
    for token in common:
        tf = block_counts[token] / len(block_tokens)
        idf = math.log(1 + len(block_tokens) / (1 + spec_counts[token]))
        score += tf * idf
    return score


def _top_blocks(spec_text: str, blocks: Iterable[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    ranked = sorted(blocks, key=lambda block: _score_block(spec_text, block.get("text", "")), reverse=True)
    return ranked[:limit]


def dispatch_spec_vendor(
    spec: Dict[str, Any],
    vendor_id: str,
    blocks: List[Dict[str, Any]],
    model_name: str = "qwen2.5-coder:1.5b",
    top_k: int = 5,
    agents: List[str] | None = None,
    fast: bool = False,
) -> Dict[str, Any]:
    requirement = (
        spec.get("company_Requirement")
        or spec.get("company_Requirement")
        or spec.get("company_requirement")
        or ""
    )
    logging.info(f"Dispatching spec {spec.get('Spec_ID','')} for vendor {vendor_id} using model {model_name}")
    if agents is None:
        agents = ["technical", "risk", "fallback"]
    top_blocks = _top_blocks(requirement, blocks, limit=top_k)
    context = "\n\n".join(block.get("text", "") for block in top_blocks)
    if len(context) > 4000:
        context = context[:4000]

    if fast:
        # Quick heuristic: check token overlap between requirement and top block
        best = top_blocks[0] if top_blocks else {}
        spec_tokens = set(_tokenize(requirement))
        block_tokens = set(_tokenize(best.get("text", "")))
        overlap = spec_tokens & block_tokens
        score = (len(overlap) / max(1, len(spec_tokens))) if spec_tokens else 0.0
        status = "YES" if score >= 0.2 else "NO"
        confidence = float(min(0.99, max(0.0, score)))
        return {
            "spec_id": spec.get("Spec_ID", ""),
            "vendor_id": vendor_id,
            "status": status,
            "citation": best.get("text", ""),
            "reasoning": f"heuristic token overlap {len(overlap)} tokens",
            "confidence": confidence,
            "citation_page": best.get("page"),
            "citation_bbox": best.get("bbox"),
            "technical": {},
            "risk": {},
            "fallback": {},
            "top_blocks": top_blocks,
        }

    futures = {}
    results = {"technical": {}, "risk": {}, "fallback": {}}
    max_workers = max(1, len(agents))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        if "technical" in agents:
            futures["technical"] = executor.submit(run_technical_agent, context, requirement, model_name)
        if "risk" in agents:
            futures["risk"] = executor.submit(run_risk_agent, context, requirement, model_name)
        if "fallback" in agents:
            futures["fallback"] = executor.submit(run_fallback_agent, context, requirement, model_name)

        for name, fut in futures.items():
            try:
                results[name] = fut.result()
            except Exception:
                results[name] = {}

    # ensure we pass three arguments to judge; missing agents are passed as empty dicts
    judged = run_consensus_judge(
        results.get("technical", {}),
        results.get("risk", {}),
        results.get("fallback", {}),
        model_name,
    )
    best_block = top_blocks[0] if top_blocks else {}
    return {
        "spec_id": spec.get("Spec_ID", ""),
        "vendor_id": vendor_id,
        "status": judged.get("status", "NO"),
        "citation": judged.get("citation", best_block.get("text", "")),
        "reasoning": judged.get("reasoning", ""),
        "confidence": float(judged.get("confidence", 0.0)),
        "citation_page": best_block.get("page"),
        "citation_bbox": best_block.get("bbox"),
        "technical": results.get("technical", {}),
        "risk": results.get("risk", {}),
        "fallback": results.get("fallback", {}),
        "top_blocks": top_blocks,
    }
