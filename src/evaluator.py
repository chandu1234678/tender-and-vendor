"""Multi-agent evaluator with DB-driven heuristic rules.

The heuristic engine loads keyword rules from the `heuristic_rules` table
so that human overrides (via the training queue) automatically improve
future evaluations without restarting the server.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    status: str
    citation: str
    reasoning: str
    confidence: float


# ── Rule loading ─────────────────────────────────────────────────────────────

def _db_path() -> str:
    from src.utils.paths import PROJECT_ROOT
    return str(PROJECT_ROOT / "data" / "parsed" / "app.db")


# ── Built-in fallback rules (used when DB is unavailable) ────────────────────
_BUILTIN_RULES: List[Tuple[str, str, float]] = [
    ("complies",     "YES",      1.0),
    ("meets",        "YES",      1.0),
    ("guarantee",    "YES",      0.9),
    ("warrant",      "YES",      0.9),
    ("confirmed",    "YES",      0.8),
    ("provided",     "YES",      0.7),
    ("included",     "YES",      0.7),
    ("rated",        "NEARLY OK", 0.7),
    ("equivalent",   "NEARLY OK", 0.7),
    ("similar",      "NEARLY OK", 0.6),
    ("partial",      "NEARLY OK", 0.6),
    ("not comply",   "NO",       1.0),
    ("does not",     "NO",       0.8),
    ("unable",       "NO",       0.8),
    ("not provided", "NO",       0.9),
    ("not included", "NO",       0.9),
]


def _load_rules(db_path: Optional[str] = None) -> List[Tuple[str, str, float]]:
    """Return list of (pattern, verdict, weight) sorted by weight desc.
    Falls back to built-in rules when the DB is unavailable or empty.
    """
    path = db_path or _db_path()
    try:
        conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
        rows = conn.execute(
            "SELECT pattern, verdict, weight FROM heuristic_rules "
            "WHERE rule_type='keyword' ORDER BY weight DESC, hit_count DESC"
        ).fetchall()
        conn.close()
        if rows:
            return [(r[0].lower(), r[1], float(r[2])) for r in rows]
    except Exception as exc:
        logger.debug("Could not load heuristic rules from DB: %s", exc)
    return _BUILTIN_RULES


def _increment_hit(pattern: str, db_path: Optional[str] = None) -> None:
    path = db_path or _db_path()
    try:
        conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
        conn.execute(
            "UPDATE heuristic_rules SET hit_count=hit_count+1, updated_at=CURRENT_TIMESTAMP "
            "WHERE pattern=? AND rule_type='keyword'",
            (pattern,),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Training queue → rule extraction ─────────────────────────────────────────

def retrain_from_feedback(db_path: Optional[str] = None) -> int:
    """Read unprocessed training_queue rows and extract new keyword rules.

    For each human-corrected example:
    - tokenise the excerpt
    - find tokens that appear in the excerpt but NOT in the original
      heuristic match → add as new keyword rules with the corrected label
    - mark the training_queue row as processed

    Returns the number of new rules added.
    """
    path = db_path or _db_path()
    added = 0
    try:
        conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
        rows = conn.execute(
            "SELECT id, excerpt, label FROM training_queue WHERE processed=0 AND excerpt IS NOT NULL AND label IS NOT NULL"
        ).fetchall()

        existing_patterns = {
            r[0] for r in conn.execute("SELECT pattern FROM heuristic_rules").fetchall()
        }

        for row_id, excerpt, label in rows:
            if not excerpt or not label:
                continue
            # extract meaningful tokens (3+ chars, alpha)
            tokens = [t for t in re.findall(r"[a-z]{3,}", excerpt.lower()) if t not in
                      {"the", "and", "for", "that", "this", "with", "from", "are", "was",
                       "has", "have", "been", "will", "shall", "not", "can", "may"}]
            # pick the 3 most distinctive tokens
            for token in tokens[:3]:
                if token in existing_patterns:
                    continue
                # weight based on label
                weight = 1.0 if label.upper().startswith("YES") else \
                         0.9 if label.upper().startswith("NO") else 0.7
                conn.execute(
                    "INSERT OR IGNORE INTO heuristic_rules "
                    "(rule_type, pattern, verdict, weight, source) VALUES (?, ?, ?, ?, 'training')",
                    ("keyword", token, label.upper(), weight),
                )
                existing_patterns.add(token)
                added += 1

            conn.execute(
                "UPDATE training_queue SET processed=1 WHERE id=?", (row_id,)
            )

        conn.commit()
        conn.close()
        if added:
            logger.info("retrain_from_feedback: added %d new rules from training queue", added)
    except Exception as exc:
        logger.error("retrain_from_feedback failed: %s", exc)
    return added


# ── Core evaluator ────────────────────────────────────────────────────────────

class MultiAgentEvaluator:
    def __init__(self, model_name: str = "llama3", db_path: Optional[str] = None) -> None:
        self.model_name = model_name
        self._db_path = db_path
        # dynamic import of ollama if available
        try:
            from ollama import generate
            self._generate = generate
        except Exception:
            self._generate = None

    def _get_rules(self) -> List[Tuple[str, str, float]]:
        return _load_rules(self._db_path)

    def _heuristic_eval(self, spec_text: str, context: str) -> EvaluationResult:
        rules = self._get_rules()
        # Extract numbers WITH their unit context (e.g. "16 gb", "4800 mt/s", "32 gb").
        # A bare number like "16" must appear followed by a non-digit/non-colon character
        # so that "16:9" (aspect ratio) does NOT match "16 GB" (memory spec).
        spec_nums = re.findall(r"\d+(?:\.\d+)?(?:\s*[a-zA-Z/%]+)?", spec_text)
        # Also keep plain numbers for fallback, but only match them as whole words
        spec_plain_nums = re.findall(r"(?<![:\d])\d+(?:\.\d+)?(?![:\d])", spec_text)
        sentences = re.split(r"(?<=[.!?])\s+", context)
        spec_hint = (spec_text or "").strip()
        if len(spec_hint) > 160:
            spec_hint = f"{spec_hint[:157]}..."

        best_status = "NO"
        best_citation = ""
        best_reasoning = "No matching clause found for the requirement."
        best_confidence = 0.0
        best_weight = 0.0

        for sentence in sentences:
            s = sentence.strip()
            if not s:
                continue
            s_lower = s.lower()

            # ── rule-based matching ──────────────────────────────────────
            for pattern, verdict, weight in rules:
                if pattern in s_lower and weight > best_weight:
                    best_weight = weight
                    best_citation = s
                    best_status = verdict
                    best_confidence = min(0.95, weight * 0.9)
                    best_reasoning = (
                        f"Rule match '{pattern}' → {verdict} "
                        f"(weight={weight:.2f}) for: {spec_hint}"
                    )
                    _increment_hit(pattern, self._db_path)

            # ── numeric match (only if no rule matched yet) ──────────────
            # Match "16 GB" style tokens — number + unit — not bare "16" in "16:9"
            if best_weight < 0.5:
                for num_token in spec_nums:
                    # num_token may be "16 GB", "4800", "32 GB" etc.
                    # Normalise spaces and check as substring in sentence lower
                    normalised = re.sub(r"\s+", " ", num_token.strip().lower())
                    if len(normalised) >= 2 and normalised in s_lower:
                        best_citation = s
                        best_status = "NEARLY OK"
                        best_confidence = 0.5
                        best_weight = 0.5
                        best_reasoning = f"Numeric match '{num_token.strip()}' found; verify: {spec_hint}"
                        break

        if best_citation and len(best_citation) > 500:
            best_citation = f"{best_citation[:497]}..."

        return EvaluationResult(
            status=best_status,
            citation=best_citation,
            reasoning=best_reasoning,
            confidence=best_confidence,
        )

    def evaluate_spec(self, vendor_id: str, spec: Dict[str, str], context: str) -> EvaluationResult:
        """Evaluate a single spec against vendor context.

        Uses Ollama if available; otherwise falls back to DB-driven heuristic rules.
        """
        requirement = spec.get("company_Requirement") or spec.get("company_requirement") or ""
        prompt = (
            f"You are a strict auditor. Requirement: {requirement}\n"
            f"Vendor context (extract): {context}\n"
            'Return JSON: {"status": "YES|NO|NEARLY OK", "citation": "...", '
            '"reasoning": "...", "confidence": 0.0}'
        )

        if self._generate:
            try:
                out = self._generate(
                    model=self.model_name, prompt=prompt, options={"temperature": 0.0}
                )
                text = out.get("response") if isinstance(out, dict) else str(out)
                j = json.loads(text.strip())
                return EvaluationResult(
                    status=j.get("status", "NO"),
                    citation=j.get("citation", ""),
                    reasoning=j.get("reasoning", ""),
                    confidence=float(j.get("confidence", 0.0)),
                )
            except Exception:
                pass

        return self._heuristic_eval(requirement, context)
