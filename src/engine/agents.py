from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional
import json
import re

from src.engine.prompts import FALLBACK_AGENT_PROMPT, RISK_AGENT_PROMPT, TECHNICAL_AGENT_PROMPT
from src.engine.ollama_client import ollama_generate, default_model
from src.evaluator import MultiAgentEvaluator


@dataclass
class AgentResult:
    status: str
    citation: str
    reasoning: str
    confidence: float


# Use default_model() so the evaluator always picks up the best available model
# from the company LM Studio server (10.5.65.131:1234) rather than a hardcoded name.
_HEURISTIC_EVALUATOR = MultiAgentEvaluator(model_name=default_model())


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
    result = _HEURISTIC_EVALUATOR._heuristic_eval(requirement, context)
    return AgentResult(
        status=result.status,
        citation=result.citation,
        reasoning=result.reasoning,
        confidence=result.confidence,
    )


def _call_ollama(prompt: str, model_name: str, temperature: float) -> Optional[Dict[str, Any]]:
    """Call Ollama via the singleton client (connection reuse + cache)."""
    text = ollama_generate(model=model_name, prompt=prompt, temperature=temperature)
    if not text:
        return None
    payload = _extract_json(text)
    return _normalize_result(payload) if payload else None


def run_technical_agent(context: str, requirement: str = "", model_name: str = "") -> Dict[str, Any]:
    if not model_name:
        model_name = default_model()
    prompt = TECHNICAL_AGENT_PROMPT.format(requirement=requirement, context=context)
    result = _call_ollama(prompt, model_name, 0.0)
    if result:
        return result
    return asdict(_heuristic_result(requirement, context))


def run_risk_agent(context: str, requirement: str = "", model_name: str = "") -> Dict[str, Any]:
    if not model_name:
        model_name = default_model()
    prompt = RISK_AGENT_PROMPT.format(requirement=requirement, context=context)
    result = _call_ollama(prompt, model_name, 0.0)
    if result:
        return result
    return asdict(_heuristic_result(requirement, context))


def run_fallback_agent(context: str, requirement: str = "", model_name: str = "") -> Dict[str, Any]:
    if not model_name:
        model_name = default_model()
    prompt = FALLBACK_AGENT_PROMPT.format(requirement=requirement, context=context)
    result = _call_ollama(prompt, model_name, 0.1)
    if result:
        return result
    return asdict(_heuristic_result(requirement, context))
