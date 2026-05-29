"""
Run the existing pipeline for product-pdf.pdf x NB01 sheet only.

Uses two filter env vars added to run_pipeline.main():
  PIPELINE_VENDOR_FILTER  -- only process product-pdf.pdf
  PIPELINE_SHEET_FILTER   -- only evaluate NB01 specs

Usage (from project root, venv active):
    python scripts/run_nb01_product_pdf.py          # heuristic only (fast, ~3s)
    $env:USE_LLM="1"; python scripts/run_nb01_product_pdf.py  # with LM Studio
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Scope filters ─────────────────────────────────────────────────────────────
os.environ["PIPELINE_VENDOR_FILTER"]   = "product-pdf"
os.environ["PIPELINE_SHEET_FILTER"]    = "NB01"

# ── Speed knobs ───────────────────────────────────────────────────────────────
os.environ["FAST_SKIP_OCR"]            = "1"
os.environ["FAST_REUSE_PARSED"]        = "1"
os.environ["FAST_TOP_K"]               = "5"
os.environ["FAST_MODE"]                = "0"
os.environ["LLM_ONLY_UNCERTAIN"]       = "1"
os.environ["PIPELINE_EVAL_WORKERS"]    = "4"
os.environ["LLM_MAX_CONCURRENT"]       = "2"

_USE_LLM = os.environ.get("USE_LLM", "0").strip() in {"1", "true", "yes"}

if _USE_LLM:
    os.environ.setdefault("LLM_BACKEND",    "lmstudio")
    os.environ.setdefault("OLLAMA_HOST",    "http://10.5.65.131:1234")
    os.environ.setdefault("OLLAMA_MODEL",   "qwen3-30b-a3b-instruct-2507")
    os.environ.setdefault("OLLAMA_TIMEOUT", "120")
    print("[INFO] LLM enabled — uncertain rows will call LM Studio")
else:
    print("[INFO] LLM disabled — pure heuristic mode (fast)")

# ── Import pipeline modules AFTER env vars are set ───────────────────────────
from src.storage.db import init_db, get_connection
from src.app.run_pipeline import main as run_pipeline

# ── If heuristic-only: patch is_healthy() to return False immediately ─────────
# This avoids any TCP connection attempt to the LM Studio server and makes
# the orchestrator skip straight to the heuristic path for every spec.
if not _USE_LLM:
    import src.engine.ollama_client as _oc
    _oc._healthy = False          # pre-set the cached health state to False
    _oc.is_healthy = lambda: False  # also patch the function itself

# ── DB setup + clear previous product-pdf results ────────────────────────────
db_path = ROOT / "data" / "parsed" / "app.db"
(ROOT / "data" / "parsed").mkdir(parents=True, exist_ok=True)
init_db(str(db_path))

conn = get_connection(str(db_path))
deleted = conn.execute(
    "DELETE FROM compliance_matrix WHERE vendor_id=?", ("product-pdf",)
).rowcount
conn.commit()
conn.close()
if deleted:
    print(f"[INFO] Cleared {deleted} previous compliance rows for product-pdf")

# ── Run ───────────────────────────────────────────────────────────────────────
run_id = f"nb01-product-pdf-{uuid.uuid4()}"
print(f"[INFO] Starting pipeline  run_id={run_id[:24]}...")
print(f"[INFO] Vendor : product-pdf.pdf   Sheet : NB01 only")
print()

run_pipeline(run_id=run_id)

# ── Print results table ───────────────────────────────────────────────────────
import sqlite3

conn2 = sqlite3.connect(str(db_path))

# Resolve which source file was used (prefer _updated variant)
_src_row = conn2.execute(
    "SELECT source_file FROM master_specs WHERE sheet_name='NB01' "
    "ORDER BY rowid DESC LIMIT 1"
).fetchone()
_src = _src_row[0] if _src_row else "%"

rows = conn2.execute(
    """
    SELECT cm.spec_id,
           COALESCE(ms.parameter_name, '') AS param,
           cm.status,
           cm.confidence,
           cm.citation_page,
           substr(COALESCE(cm.citation,''), 1, 70) AS cite
    FROM compliance_matrix cm
    LEFT JOIN master_specs ms
           ON ms.spec_id = cm.spec_id AND ms.source_file = ?
    WHERE cm.vendor_id = 'product-pdf'
    GROUP BY cm.spec_id
    ORDER BY cm.spec_id
    """,
    (_src,),
).fetchall()
conn2.close()

G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; B = "\033[1m"; X = "\033[0m"
STATUS_COL = {"YES": G, "NEARLY OK": Y, "NO": R}

yes    = sum(1 for r in rows if str(r[2]).upper().startswith("YES"))
nearly = sum(1 for r in rows if str(r[2]).upper().startswith("NEARLY"))
no     = sum(1 for r in rows if str(r[2]).upper().startswith("NO"))
score  = round((yes * 2 + nearly) / max(1, len(rows) * 2) * 100, 1)

print(f"\n{B}{'='*74}{X}")
print(f"{B}RESULTS  NB01 x product-pdf{X}")
print(f"{'='*74}")
print(f"  Specs evaluated : {len(rows)}")
print(f"  {G}YES{X}             : {yes}")
print(f"  {Y}NEARLY OK{X}       : {nearly}")
print(f"  {R}NO{X}              : {no}")
print(f"  Compliance score: {score}%")
print(f"{'='*74}")
print(f"\n{B}{'Spec ID':<14} {'Parameter':<24} {'Status':<12} {'Conf':>5}  {'Pg':>3}  Citation{X}")
print("-" * 92)
for spec_id, param, status, conf, page, cite in rows:
    col = STATUS_COL.get(str(status).upper().strip(), "")
    cite_str = (cite or "").replace("\n", " ").strip()
    print(
        f"{spec_id:<14} {param[:23]:<24} "
        f"{col}{status:<12}{X} {conf:>5.2f}  {str(page or '-'):>3}  {cite_str}"
    )

print()
print(f"[INFO] Excel reports written to data/output/")
print(f"[INFO] Run ID: {run_id}")
