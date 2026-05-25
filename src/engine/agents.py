from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional
import json
import re

from src.engine.prompts import FALLBACK_AGENT_PROMPT, RISK_AGENT_PROMPT, TECHNICAL_AGENT_PROMPT
from src.evaluator import MultiAgentEvaluator


@dataclass
class AgentResult:
    status: str
    citation: str
    reasoning: str
    confidence: float


def _normalize_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": str(payload.get("status", "NO")).strip() or "NO",
        "citation": str(payload.get("citation", "")),
        "reasoning": str(payload.get("reasoning", "")),
        "confidence": float(payload.get("confidence", 0.0) or 0.0),
    }


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


def _heuristic_result(requirement: str, context: str) -> AgentResult:
    evaluator = MultiAgentEvaluator(model_name="llama3")
    result = evaluator._heuristic_eval(requirement, context)
    return AgentResult(
        status=result.status,
        citation=result.citation,
        reasoning=result.reasoning,
        confidence=result.confidence,
    )


def _call_ollama(prompt: str, model_name: str, temperature: float) -> Optional[Dict[str, Any]]:
    try:
        from ollama import generate

        response = generate(model=model_name, prompt=prompt, options={"temperature": temperature})
        text = response.get("response") if isinstance(response, dict) else str(response)
        payload = _extract_json(text)
        return _normalize_result(payload or {}) if payload else None
    except Exception:
        return None


def run_technical_agent(context: str, requirement: str = "", model_name: str = "llama3") -> Dict[str, Any]:
    prompt = f"{TECHNICAL_AGENT_PROMPT}\n\nRequirement:\n{requirement}\n\nContext:\n{context}"
    result = _call_ollama(prompt, model_name, 0.0)
    if result:
        return result
    return asdict(_heuristic_result(requirement, context))


def run_risk_agent(context: str, requirement: str = "", model_name: str = "llama3") -> Dict[str, Any]:
    prompt = f"{RISK_AGENT_PROMPT}\n\nRequirement:\n{requirement}\n\nContext:\n{context}"
    result = _call_ollama(prompt, model_name, 0.0)
    if result:
        return result
    return asdict(_heuristic_result(requirement, context))


def run_fallback_agent(context: str, requirement: str = "", model_name: str = "llama3") -> Dict[str, Any]:
    prompt = f"{FALLBACK_AGENT_PROMPT}\n\nRequirement:\n{requirement}\n\nContext:\n{context}"
    result = _call_ollama(prompt, model_name, 0.1)
    if result:
        return result
    return asdict(_heuristic_result(requirement, context))
