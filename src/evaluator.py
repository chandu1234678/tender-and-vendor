from __future__ import annotations

from dataclasses import dataclass
from typing import Dict
import json
import re


@dataclass
class EvaluationResult:
    status: str
    citation: str
    reasoning: str
    confidence: float


class MultiAgentEvaluator:
    def __init__(self, model_name: str = "llama3") -> None:
        self.model_name = model_name
        # dynamic import of ollama if available
        try:
            from ollama import generate

            self._generate = generate
        except Exception:
            self._generate = None

    def _heuristic_eval(self, spec_text: str, context: str) -> EvaluationResult:
        # Simple heuristics: look for numeric matches or keywords
        spec_nums = re.findall(r"\d+\.?\d*", spec_text)
        # find a nearby sentence containing spec key terms
        sentences = re.split(r"(?<=[.!?])\s+", context)
        citation = ""
        status = "NO"
        reasoning = "No matching clause found for the requirement."
        confidence = 0.0
        spec_hint = (spec_text or "").strip()
        if len(spec_hint) > 160:
            spec_hint = f"{spec_hint[:157]}..."
        for s in sentences:
            if not s.strip():
                continue
            if any(term.lower() in s.lower() for term in ["complies", "meets", "guarantee", "warrant"]):
                citation = s.strip()
                status = "YES"
                reasoning = f"Compliance language found for requirement: {spec_hint}"
                confidence = 0.8
                break
            if "rated" in s.lower():
                citation = s.strip()
                status = "NEARLY OK"
                reasoning = f"Rated language found; verify equivalence for requirement: {spec_hint}"
                confidence = 0.55
                break
            # numeric match heuristic
            for n in spec_nums:
                if n in s:
                    citation = s.strip()
                    status = "NEARLY OK"
                    reasoning = f"Numeric match {n} found; verify requirement: {spec_hint}"
                    confidence = 0.5
                    break
            if status != "NO":
                break
        if citation and len(citation) > 200:
            citation = f"{citation[:197]}..."
        return EvaluationResult(status=status, citation=citation or "", reasoning=reasoning, confidence=confidence)

    def evaluate_spec(self, vendor_id: str, spec: Dict[str, str], context: str) -> EvaluationResult:
        """Evaluate a single spec against vendor context.

        Uses Ollama if available; otherwise falls back to heuristic rules.
        """
        requirement = spec.get('company_Requirement') or spec.get('company_Requirement') or spec.get('company_requirement') or ''
        prompt = (
            f"You are a strict auditor. Requirement: {requirement}\n"
            f"Vendor context (extract): {context}\n"
            "Return JSON: {\"compliance\": \"YES|NO|NEARLY OK\", \"citation\": \"...\", \"reasoning\": \"...\", \"confidence\": 0.0}"
        )

        if self._generate:
            try:
                out = self._generate(model=self.model_name, prompt=prompt, options={"temperature": 0.0})
                text = out.get("response") if isinstance(out, dict) else str(out)
                # try to find JSON in the response
                j = json.loads(text.strip())
                return EvaluationResult(status=j.get("compliance", "NO"), citation=j.get("citation", ""), reasoning=j.get("reasoning", ""), confidence=float(j.get("confidence", 0.0)))
            except Exception:
                # fall back to heuristic
                return self._heuristic_eval(requirement, context)
        else:
            return self._heuristic_eval(requirement, context)
