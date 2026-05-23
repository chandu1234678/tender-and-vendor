from __future__ import annotations

from typing import Any, Dict, List
import json

from src.engine.prompts import JUDGE_PROMPT


def _score(status: str) -> int:
    normalized = (status or "").strip().upper()
    if normalized.startswith("YES"):
        return 2
    if normalized.startswith("NEARLY"):
        return 1
    return 0


def _heuristic_judge(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    best = max(results, key=lambda item: (_score(item.get("status")), float(item.get("confidence", 0.0))))
    return {
        "status": best.get("status", "NO"),
        "citation": best.get("citation", ""),
        "reasoning": f"Consensus chosen from agent results: {best.get('reasoning', '')}".strip(),
        "confidence": float(best.get("confidence", 0.0)),
    }


def run_consensus_judge(technical: Dict[str, Any], risk: Dict[str, Any], fallback: Dict[str, Any], model_name: str = "llama3") -> Dict[str, Any]:
    payload = [technical, risk, fallback]
    prompt = f"{JUDGE_PROMPT}\n\nAgent results:\n{json.dumps(payload, ensure_ascii=False)}"
    try:
        from ollama import generate

        response = generate(model=model_name, prompt=prompt, options={"temperature": 0.0})
        text = response.get("response") if isinstance(response, dict) else str(response)
        parsed = json.loads(text.strip())
        return {
            "status": parsed.get("status", "NO"),
            "citation": parsed.get("citation", ""),
            "reasoning": parsed.get("reasoning", ""),
            "confidence": float(parsed.get("confidence", 0.0)),
        }
    except Exception:
        return _heuristic_judge(payload)
