from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
import math
import os
import re
import json
import threading

from src.engine.agents import run_fallback_agent, run_risk_agent, run_technical_agent
from src.engine.ollama_client import default_model, ollama_generate, is_healthy
import logging
from src.engine.judge import run_consensus_judge, _extract_json, _decision_rule
from src.engine.prompts import FAST_EVAL_PROMPT

_dispatch_stats_lock = threading.Lock()
_dispatch_stats: Dict[str, int] = {
    "quick": 0,
    "heuristic": 0,
    "fast": 0,
    "llm_single": 0,
    "llm_multi": 0,
}


def get_dispatch_stats() -> Dict[str, int]:
    with _dispatch_stats_lock:
        return dict(_dispatch_stats)


def reset_dispatch_stats() -> None:
    with _dispatch_stats_lock:
        for key in _dispatch_stats:
            _dispatch_stats[key] = 0


def _record_dispatch(path: str) -> None:
    with _dispatch_stats_lock:
        _dispatch_stats[path] = _dispatch_stats.get(path, 0) + 1


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _tokenize(text: str) -> List[str]:
    return [token for token in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(token) > 1]


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split())


def _make_dispatch_result(
    spec_id: str,
    vendor_id: str,
    status: str,
    citation: str,
    reasoning: str,
    confidence: float,
    citation_page: Optional[int] = None,
    citation_bbox: Optional[List[float]] = None,
    technical: Optional[Dict[str, Any]] = None,
    risk: Optional[Dict[str, Any]] = None,
    fallback: Optional[Dict[str, Any]] = None,
    top_blocks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return a canonical dispatch result with consistent keys.

    Ensures `technical`, `risk`, and `fallback` are dicts with at least
    `status` and `confidence` keys (or empty dicts) so downstream DB inserts
    and consumers don't see shape variance.
    """
    technical = technical or {}
    risk = risk or {}
    fallback = fallback or {}
    def _norm_agent(a: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(a, dict):
            return {}
        return {
            "status": a.get("status"),
            "confidence": float(a.get("confidence", 0.0)) if a.get("confidence") is not None else None,
            **{k: v for k, v in a.items() if k not in {"status", "confidence"}},
        }

    return {
        "spec_id": spec_id,
        "vendor_id": vendor_id,
        "status": status,
        "citation": citation,
        "reasoning": reasoning,
        "confidence": float(confidence or 0.0),
        "citation_page": citation_page,
        "citation_bbox": citation_bbox,
        "technical": _norm_agent(technical),
        "risk": _norm_agent(risk),
        "fallback": _norm_agent(fallback),
        "top_blocks": top_blocks or [],
    }


@dataclass(frozen=True)
class VendorIndex:
    blocks: Tuple[Dict[str, Any], ...]
    block_tokens: Tuple[Tuple[str, ...], ...]
    block_token_counts: Tuple[Counter, ...]
    idf: Dict[str, float]
    avg_block_len: float
    block_texts_norm: Tuple[str, ...]

    @classmethod
    def build(cls, blocks: Sequence[Dict[str, Any]]) -> "VendorIndex":
        block_list = [dict(block) for block in blocks]
        block_tokens: List[List[str]] = []
        block_token_counts: List[Counter] = []
        block_texts_norm: List[str] = []
        doc_freq: Counter = Counter()
        total_len = 0

        for block in block_list:
            text = str(block.get("text", ""))
            tokens = _tokenize(text)
            token_counts = Counter(tokens)
            block_tokens.append(tokens)
            block_token_counts.append(token_counts)
            block_texts_norm.append(_normalize_text(text))
            total_len += len(tokens)
            doc_freq.update(set(tokens))

        total_docs = max(1, len(block_tokens))
        avg_block_len = total_len / total_docs if total_docs else 0.0
        idf = {
            token: math.log((total_docs + 1) / (1 + freq)) + 1
            for token, freq in doc_freq.items()
        }
        return cls(
            blocks=tuple(block_list),
            block_tokens=tuple(tuple(bt) for bt in block_tokens),
            block_token_counts=tuple(block_token_counts),
            idf=idf,
            avg_block_len=avg_block_len,
            block_texts_norm=tuple(block_texts_norm),
        )


def _score_block_with_index(spec_counts: Counter, block_counts: Counter, block_len: int, index: VendorIndex) -> float:
    if not spec_counts or not block_counts:
        return 0.0
    common = set(spec_counts) & set(block_counts)
    if not common:
        return 0.0
    k1 = 1.5
    b = 0.75
    avg_len = max(1.0, index.avg_block_len)
    score = 0.0
    for token in common:
        idf = index.idf.get(token, 0.0)
        if idf == 0.0:
            continue
        term_freq = block_counts[token]
        denom = term_freq + k1 * (1 - b + b * (block_len / avg_len))
        score += idf * ((term_freq * (k1 + 1)) / denom)
    return score


def _extract_spec_numbers(text: str) -> set:
    """Extract numbers with their unit context to avoid false ratio matches.

    "Minimum 16 GB DDR5 RAM 4800 MT/s" → {"16 gb", "4800 mt/s", "32 gb"}
    "Native aspect ratio 16:9"          → {} (16:9 is a ratio, not a spec value)

    A number is considered a spec value when it is:
      - followed by a unit (letters/%) with optional space, OR
      - a standalone integer not immediately followed or preceded by ':'
    """
    results: set = set()
    # Match number + unit (e.g. "16 GB", "4800MT/s", "1 TB", "230V")
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*([a-zA-Z/%]+)", text):
        results.add(f"{m.group(1)} {m.group(2).lower()}")
    # Match standalone numbers not part of a ratio (not preceded/followed by ':')
    for m in re.finditer(r"(?<![:\d\.])(\d+(?:\.\d+)?)(?![:\d])", text):
        results.add(m.group(1))
    return results


def _numeric_magnitude_ok(requirement: str, evidence_text: str) -> bool:
    """Check that every number+unit in the requirement is satisfied by the evidence.

    For specs with "minimum", "or higher", "or more", "at least":
      evidence value must be >= requirement value (same unit).
    For all other specs:
      evidence value must be >= requirement value (lenient — catches "equivalent").

    Returns True if all requirement numbers are satisfied or if no numbers found.
    Returns False if any required number is clearly NOT met (e.g. 1 MB vs 12 MB).
    """
    req_lower = requirement.lower()
    is_minimum = any(kw in req_lower for kw in (
        "minimum", "or higher", "or more", "at least", "min ", "min.", "upto", "up to"
    ))

    # Extract (value, unit) pairs from requirement
    req_pairs: List[Tuple[float, str]] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]+)", requirement):
        try:
            req_pairs.append((float(m.group(1)), m.group(2).lower()))
        except ValueError:
            pass

    if not req_pairs:
        return True  # no numeric requirement to check

    ev_lower = evidence_text.lower()
    for req_val, req_unit in req_pairs:
        # Find all evidence values with the same unit
        ev_vals: List[float] = []
        for m in re.finditer(
            r"(\d+(?:\.\d+)?)\s*" + re.escape(req_unit) + r"\b",
            ev_lower,
        ):
            try:
                ev_vals.append(float(m.group(1)))
            except ValueError:
                pass

        if not ev_vals:
            # Unit not found in evidence at all — requirement cannot be confirmed
            return False

        best_ev = max(ev_vals)
        if is_minimum:
            # Evidence must meet or exceed the requirement
            if best_ev < req_val:
                return False
        else:
            # Exact or better — evidence must be >= requirement
            if best_ev < req_val * 0.9:  # 10% tolerance for rounding
                return False

    return True


def _verify_citation(citation: str, top_blocks_norm: Sequence[str], fallback: str = "") -> str:
    """Return citation if it appears verbatim in one of the top blocks, else fallback."""
    normalized = _normalize_text(citation)
    if not normalized:
        return fallback
    for block_text in top_blocks_norm:
        if normalized in block_text:
            return citation
    return fallback


def _top_blocks_from_index(spec_text: str, index: VendorIndex, limit: int = 5) -> Tuple[List[Dict[str, Any]], List[str]]:
    spec_tokens = _tokenize(spec_text)
    if not spec_tokens:
        return [], []
    spec_counts = Counter(spec_tokens)
    scored: List[Tuple[float, int]] = []
    for idx, block_counts in enumerate(index.block_token_counts):
        block_len = len(index.block_tokens[idx])
        score = _score_block_with_index(spec_counts, block_counts, block_len, index)
        scored.append((score, idx))
    scored.sort(key=lambda item: item[0], reverse=True)
    top_indices = [idx for _, idx in scored[:limit]]
    return [dict(index.blocks[idx]) for idx in top_indices], [index.block_texts_norm[idx] for idx in top_indices]


def _trim_context(context: str, max_chars: int = 3500) -> str:
    """Trim context to max_chars, cutting at a sentence boundary.

    Default is 3500 chars — large enough to preserve meaningful vendor
    paragraphs while keeping prompts reasonably sized.
    """
    if len(context) <= max_chars:
        return context
    trimmed = context[:max_chars]
    sentence_end = max(trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"))
    if sentence_end >= max_chars * 0.5:
        return trimmed[: sentence_end + 1]
    return trimmed.rstrip()


def _quick_evidence_verdict(requirement: str, top_blocks: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a high-confidence verdict for obvious evidence."""
    if not requirement or not top_blocks:
        return None

    best = top_blocks[0]
    text = str(best.get("text", ""))
    lower_text = text.lower()
    positive_markers = (
        "complies",
        "compliant",
        "meets",
        "yes",
        "as per specification",
        "as per tender",
        "provided",
        "included",
        "available",
        "supported",
    )
    if not any(marker in lower_text for marker in positive_markers):
        return None

    req_tokens = set(_tokenize(requirement))
    evidence_tokens = set(_tokenize(text))
    if not req_tokens:
        return None

    overlap = req_tokens & evidence_tokens
    overlap_ratio = len(overlap) / max(1, len(req_tokens))
    req_numbers = _extract_spec_numbers(requirement)
    evidence_numbers = _extract_spec_numbers(text)
    numbers_ok = not req_numbers or req_numbers <= evidence_numbers

    if overlap_ratio >= 0.18 and numbers_ok:
        return {
            "status": "YES",
            "citation": text,
            "reasoning": f"Fast evidence match: {len(overlap)} requirement terms found in cited context.",
            "confidence": float(min(0.98, 0.72 + overlap_ratio)),
        }
    return None


def _heuristic_overlap_eval(
    requirement: str,
    top_blocks: Sequence[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """High-confidence token overlap — skips LLM when LLM_ONLY_UNCERTAIN is enabled."""
    if not requirement or not top_blocks:
        return None

    best = top_blocks[0]
    text = str(best.get("text", ""))
    if not text.strip():
        return None

    spec_tokens = set(_tokenize(requirement))
    block_tokens = set(_tokenize(text))
    if not spec_tokens:
        return None

    overlap = spec_tokens & block_tokens
    overlap_ratio = len(overlap) / max(1, len(spec_tokens))
    req_numbers = _extract_spec_numbers(requirement)
    evidence_numbers = _extract_spec_numbers(text)
    numbers_ok = not req_numbers or req_numbers <= evidence_numbers

    yes_threshold = _float_env("HEURISTIC_YES_RATIO", 0.25)
    no_threshold = _float_env("HEURISTIC_NO_RATIO", 0.08)

    if overlap_ratio >= yes_threshold and numbers_ok:
        confidence = float(min(0.96, 0.68 + overlap_ratio))
        return {
            "status": "YES",
            "citation": text,
            "reasoning": f"Heuristic match: {len(overlap)}/{len(spec_tokens)} requirement terms in top evidence.",
            "confidence": confidence,
        }

    if overlap_ratio <= no_threshold:
        return {
            "status": "NO",
            "citation": text[:500],
            "reasoning": f"Heuristic: weak evidence overlap ({len(overlap)}/{len(spec_tokens)} terms).",
            "confidence": float(min(0.92, 0.75 + (no_threshold - overlap_ratio))),
        }

    return None


def _using_default_agents() -> bool:
    """Tests monkeypatch these callables; keep that path explicitly testable."""
    return (
        getattr(run_technical_agent, "__module__", "") == "src.engine.agents"
        and getattr(run_risk_agent, "__module__", "") == "src.engine.agents"
        and getattr(run_fallback_agent, "__module__", "") == "src.engine.agents"
    )


def _single_call_dispatch(
    requirement: str,
    context: str,
    model_name: str,
) -> Optional[Dict[str, Any]]:
    """One Ollama call instead of 3 agents + 1 judge.

    Used for small models (<=3B) where 4 sequential calls are too slow.
    Falls back to None so the caller can use the heuristic path.
    """
    prompt = FAST_EVAL_PROMPT.format(requirement=requirement, context=context)
    text = ollama_generate(model=model_name, prompt=prompt, temperature=0.0, max_tokens=200)
    if not text:
        return None
    parsed = _extract_json(text)
    if not parsed:
        return None
    status = str(parsed.get("status", "")).strip().upper()
    if status not in {"YES", "NO", "NEARLY OK"}:
        return None
    return {
        "status": status,
        "citation": str(parsed.get("citation", "")),
        "reasoning": str(parsed.get("reasoning", "")),
        "confidence": float(parsed.get("confidence", 0.5) or 0.5),
    }


def dispatch_spec_vendor(
    spec: Dict[str, Any],
    vendor_id: str,
    blocks: List[Dict[str, Any]],
    vendor_index: Optional[VendorIndex] = None,
    model_name: str | None = None,
    top_k: int = 5,
    agents: List[str] | None = None,
    fast: bool = False,
) -> Dict[str, Any]:
    requirement = (
        spec.get("company_Requirement")
        or spec.get("company_requirement")
        or ""
    )
    spec_id = spec.get("Spec_ID", "")
    if not model_name:
        model_name = default_model()
    logging.debug("Dispatching %s for %s (model=%s)", spec_id, vendor_id, model_name)

    if agents is None:
        agents = ["technical", "risk", "fallback"]
    if vendor_index is None:
        logging.warning("VendorIndex not provided; building per spec (slow path)")
        vendor_index = VendorIndex.build(blocks)

    top_blocks, top_blocks_norm = _top_blocks_from_index(requirement, vendor_index, limit=top_k)
    context = "\n\n".join(block.get("text", "") for block in top_blocks)
    context = _trim_context(context)  # 1500 chars — fast for small models

    # ── fast heuristic path (no Ollama) ─────────────────────────────────────
    allow_model_shortcuts = _using_default_agents()

    quick = _quick_evidence_verdict(requirement, top_blocks) if allow_model_shortcuts else None
    if quick:
        _record_dispatch("quick")
        best_block = top_blocks[0] if top_blocks else {}
        return _make_dispatch_result(
            spec_id,
            vendor_id,
            quick["status"],
            quick["citation"],
            quick["reasoning"],
            quick["confidence"],
            citation_page=best_block.get("page"),
            citation_bbox=best_block.get("bbox"),
            technical={"status": quick["status"], "confidence": quick["confidence"]},
            risk={},
            fallback={},
            top_blocks=top_blocks,
        )

    if fast:
        _record_dispatch("fast")
        best = top_blocks[0] if top_blocks else {}
        best_text = best.get("text", "")
        spec_tokens = set(_tokenize(requirement))
        block_tokens = set(_tokenize(best_text))
        overlap = spec_tokens & block_tokens
        score = (len(overlap) / max(1, len(spec_tokens))) if spec_tokens else 0.0

        # Numeric magnitude check: "1 MB cache" must NOT satisfy "12 MB cache or higher"
        magnitude_ok = _numeric_magnitude_ok(requirement, best_text)

        if score >= 0.2 and magnitude_ok:
            status = "YES"
        elif score >= 0.2 and not magnitude_ok:
            status = "NO"   # token overlap but numbers don't satisfy requirement
        else:
            status = "NO"

        return _make_dispatch_result(
            spec_id,
            vendor_id,
            status,
            best_text,
            (
                f"heuristic token overlap {len(overlap)} tokens"
                + ("" if magnitude_ok else "; numeric values do not meet requirement")
            ),
            float(min(0.99, max(0.0, score))) if magnitude_ok else 0.85,
            citation_page=best.get("page"),
            citation_bbox=best.get("bbox"),
            technical={},
            risk={},
            fallback={},
            top_blocks=top_blocks,
        )

    if allow_model_shortcuts and _bool_env("LLM_ONLY_UNCERTAIN", False):
        heuristic = _heuristic_overlap_eval(requirement, top_blocks)
        if heuristic:
            _record_dispatch("heuristic")
            best_block = top_blocks[0] if top_blocks else {}
            citation = _verify_citation(heuristic.get("citation", ""), top_blocks_norm, best_block.get("text", ""))
            return _make_dispatch_result(
                spec_id,
                vendor_id,
                heuristic["status"],
                citation,
                heuristic.get("reasoning", ""),
                heuristic.get("confidence", 0.5),
                citation_page=best_block.get("page"),
                citation_bbox=best_block.get("bbox"),
                technical={"status": heuristic["status"], "confidence": heuristic.get("confidence", 0.5)},
                risk={},
                fallback={},
                top_blocks=top_blocks,
            )

    # ── single-call LLM path (1 call instead of 4) ──────────────────────────
    if allow_model_shortcuts and is_healthy():
        logging.info("LLM eval %s x %s (uncertain — ~30s possible)", spec_id, vendor_id)
        judged = _single_call_dispatch(requirement, context, model_name)
        if judged:
            _record_dispatch("llm_single")
            best_block = top_blocks[0] if top_blocks else {}
            citation = _verify_citation(judged.get("citation", ""), top_blocks_norm, best_block.get("text", ""))
            return _make_dispatch_result(
                spec_id,
                vendor_id,
                judged["status"],
                citation,
                judged.get("reasoning", ""),
                judged.get("confidence", 0.5),
                citation_page=best_block.get("page"),
                citation_bbox=best_block.get("bbox"),
                technical={"status": judged["status"], "confidence": judged.get("confidence", 0.5)},
                risk={},
                fallback={},
                top_blocks=top_blocks,
            )

    # ── multi-agent path (fallback when single-call fails or LLM is down) ───
    _record_dispatch("llm_multi")
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

    judged = run_consensus_judge(
        results.get("technical", {}),
        results.get("risk", {}),
        results.get("fallback", {}),
        model_name,
    )
    best_block = top_blocks[0] if top_blocks else {}
    citation = _verify_citation(judged.get("citation", ""), top_blocks_norm, best_block.get("text", ""))
    return {
        "spec_id": spec_id,
        "vendor_id": vendor_id,
        "status": judged.get("status", "NO"),
        "citation": citation,
        "reasoning": judged.get("reasoning", ""),
        "confidence": float(judged.get("confidence", 0.0)),
        "citation_page": best_block.get("page"),
        "citation_bbox": best_block.get("bbox"),
        "technical": results.get("technical", {}),
        "risk": results.get("risk", {}),
        "fallback": results.get("fallback", {}),
        "top_blocks": top_blocks,
    }
