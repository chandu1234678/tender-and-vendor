from __future__ import annotations

from typing import Any, Dict, List, Optional
import json
import re

from src.engine.prompts import JUDGE_PROMPT


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n|```$", "", cleaned.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def _decision_rule(technical: Dict[str, Any], risk: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    tech_status = str(technical.get("status", "NO")).strip().upper()
    risk_status = str(risk.get("status", "NO")).strip().upper()
    fallback_status = str(fallback.get("status", "NO")).strip().upper()
    status = "NEARLY OK"
    if tech_status.startswith("YES") and (risk_status.startswith("YES") or fallback_status.startswith("YES")):
        status = "YES"
    elif tech_status.startswith("NO") and risk_status.startswith("NO"):
        status = "NO"

    chosen = technical if status == tech_status else risk if status == risk_status else fallback
    return {
        "status": status,
        "citation": chosen.get("citation", ""),
        "reasoning": f"Consensus rule applied: {status}. {chosen.get('reasoning', '')}".strip(),
        "confidence": float(chosen.get("confidence", 0.0)),
    }


def run_consensus_judge(technical: Dict[str, Any], risk: Dict[str, Any], fallback: Dict[str, Any], model_name: str = "llama3") -> Dict[str, Any]:
    payload = [technical, risk, fallback]
    prompt = f"{JUDGE_PROMPT}\n\nAgent results:\n{json.dumps(payload, ensure_ascii=False)}"
    try:
        from ollama import generate

        response = generate(model=model_name, prompt=prompt, options={"temperature": 0.0})
        text = response.get("response") if isinstance(response, dict) else str(response)
        parsed = _extract_json(text)
        if parsed:
            return {
                "status": parsed.get("status", "NO"),
                "citation": parsed.get("citation", ""),
                "reasoning": parsed.get("reasoning", ""),
                "confidence": float(parsed.get("confidence", 0.0)),
            }
    except Exception:
        pass
    return _decision_rule(technical, risk, fallback)
