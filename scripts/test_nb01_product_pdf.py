"""
Test pipeline: product-pdf.pdf  x  NB01 sheet only
====================================================
Runs the full compliance evaluation for the NB01 sheet of
Tech_Comp_check_list_updated.xlsx against data/incoming/product-pdf.pdf.

Speed mode (default): pure heuristic — no LLM calls, completes in <5 s.
LLM mode:  set env var USE_LLM=1 before running to enable LM Studio calls.

Usage (from project root, venv active):
    python scripts/test_nb01_product_pdf.py          # fast heuristic
    USE_LLM=1 python scripts/test_nb01_product_pdf.py  # with LLM

Output:
  - Console table: spec row | parameter | requirement | status | confidence | citation snippet
  - data/output/test_nb01_product_pdf_<timestamp>.xlsx  (Matrix + Details + Summary)
  - data/output/vendor_product-pdf_<timestamp>.xlsx     (filled-in template clone)
  - data/parsed/app.db                                  (SQLite rows for this run)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── make sure project root is on sys.path ────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Speed vs accuracy toggle ─────────────────────────────────────────────────
# Default: pure heuristic (no LLM) — fast, deterministic, works offline.
# Set USE_LLM=1 in your shell to enable LM Studio calls for uncertain rows.
_USE_LLM = os.environ.get("USE_LLM", "0").strip() in {"1", "true", "yes"}

# Force heuristic-only path unless caller explicitly opts in to LLM
os.environ["FAST_MODE"]          = "0"
os.environ["FAST_SKIP_OCR"]      = "1"   # PDF has native text — OCR not needed
os.environ["FAST_REUSE_PARSED"]  = "1"   # reuse cached PDF blocks from DB
os.environ["FAST_TOP_K"]         = "5"   # top-5 BM25 blocks per spec
os.environ["LLM_ONLY_UNCERTAIN"] = "0" if _USE_LLM else "1"
os.environ["PIPELINE_EVAL_WORKERS"] = "4"
os.environ["LLM_MAX_CONCURRENT"]    = "2"

if _USE_LLM:
    os.environ.setdefault("LLM_BACKEND",    "lmstudio")
    os.environ.setdefault("OLLAMA_HOST",    "http://10.5.65.131:1234")
    os.environ.setdefault("OLLAMA_MODEL",   "qwen3-30b-a3b-instruct-2507")
    os.environ.setdefault("OLLAMA_TIMEOUT", "120")
else:
    # Disable LLM entirely — heuristic fallback always fires
    os.environ["LLM_BACKEND"] = "none"   # unknown backend → is_healthy() returns False

from src.ingest.excel_parser import parse_master_excel
from src.ingest.pdf_parser import parse_pdf_blocks
from src.storage.db import init_db, get_connection
from src.engine.ollama_client import default_model, is_healthy
from src.engine.orchestrator import VendorIndex, dispatch_spec_vendor
from src.evaluator import MultiAgentEvaluator
from src.reporting.excel_report import build_excel_report
from src.utils.logging import setup_logging

# ── paths ────────────────────────────────────────────────────────────────────
INCOMING   = ROOT / "data" / "incoming"
PARSED_DIR = ROOT / "data" / "parsed"
OUTPUT_DIR = ROOT / "data" / "output"
DB_PATH    = PARSED_DIR / "app.db"

VENDOR_PDF  = INCOMING / "product-pdf.pdf"
MASTER_XLSX = INCOMING / "Tech_Comp_check_list_updated.xlsx"
TARGET_SHEET = "NB01"
VENDOR_ID    = VENDOR_PDF.stem          # "product-pdf"

# ── colour codes for terminal output ─────────────────────────────────────────
_GREEN  = "\033[92m"
_YELLOW = "\033[93m"
_RED    = "\033[91m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"

STATUS_COLOUR = {
    "YES":      _GREEN,
    "NEARLY OK": _YELLOW,
    "NO":       _RED,
}


def _colour(status: str) -> str:
    c = STATUS_COLOUR.get(status.upper().strip(), "")
    return f"{c}{status}{_RESET}" if c else status


def _truncate(text: str, n: int = 80) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:n] + "…" if len(text) > n else text


def main() -> None:
    setup_logging()
    logging.info("=== NB01 x product-pdf test pipeline ===")

    # ── setup dirs + DB ──────────────────────────────────────────────────────
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    init_db(str(DB_PATH))

    # ── validate inputs ──────────────────────────────────────────────────────
    if not VENDOR_PDF.exists():
        sys.exit(f"[ERROR] Vendor PDF not found: {VENDOR_PDF}")
    if not MASTER_XLSX.exists():
        sys.exit(f"[ERROR] Master Excel not found: {MASTER_XLSX}")

    run_id = f"test-nb01-{uuid.uuid4()}"
    conn = get_connection(str(DB_PATH))
    cur  = conn.cursor()

    # register run
    cur.execute(
        "INSERT OR REPLACE INTO pipeline_runs "
        "(run_id, status, progress, message, error, updated_at) "
        "VALUES (?, 'running', 0, 'NB01 test started', '', CURRENT_TIMESTAMP)",
        (run_id,),
    )
    conn.commit()

    # ── Step 1: parse NB01 sheet only ────────────────────────────────────────
    print(f"\n{_BOLD}[1/4] Parsing NB01 sheet from {MASTER_XLSX.name}{_RESET}")
    all_specs = parse_master_excel(str(MASTER_XLSX), db_conn=conn)
    nb01_specs = [s for s in all_specs if s.get("sheet_name") == TARGET_SHEET]

    if not nb01_specs:
        sys.exit(f"[ERROR] No specs found for sheet '{TARGET_SHEET}' in {MASTER_XLSX.name}")

    print(f"  → {len(nb01_specs)} spec rows found in {TARGET_SHEET}")

    # persist specs to master_specs table
    cur.execute("DELETE FROM master_specs WHERE source_file=? AND sheet_name=?",
                (MASTER_XLSX.name, TARGET_SHEET))
    for idx, spec in enumerate(nb01_specs, start=1):
        cur.execute(
            "INSERT OR REPLACE INTO master_specs "
            "(source_file, sheet_name, spec_id, parameter_name, company_requirement, row_index) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                MASTER_XLSX.name,
                spec.get("sheet_name", TARGET_SHEET),
                spec.get("Spec_ID", ""),
                spec.get("Parameter_Name", ""),
                spec.get("company_Requirement") or spec.get("company_requirement", ""),
                spec.get("row_index", idx),
            ),
        )
    conn.commit()

    # ── Step 2: parse vendor PDF (reuse cached blocks if available) ───────────
    print(f"\n{_BOLD}[2/4] Parsing vendor PDF: {VENDOR_PDF.name}{_RESET}")
    existing_count = cur.execute(
        "SELECT COUNT(*) FROM parsed_documents WHERE file_name=?",
        (VENDOR_PDF.name,),
    ).fetchone()[0]

    if existing_count and os.environ.get("FAST_REUSE_PARSED", "1") == "1":
        print(f"  → Reusing {existing_count} cached blocks from DB")
        rows = cur.execute(
            "SELECT page, bbox, text FROM parsed_documents "
            "WHERE file_name=? ORDER BY page, doc_id",
            (VENDOR_PDF.name,),
        ).fetchall()
        blocks = []
        for page, bbox, text in rows:
            try:
                parsed_bbox = json.loads(bbox)
            except Exception:
                parsed_bbox = bbox
            blocks.append({"page": page, "bbox": parsed_bbox, "text": text})
    else:
        blocks = parse_pdf_blocks(str(VENDOR_PDF))
        print(f"  → Parsed {len(blocks)} text blocks from PDF")
        # store in DB
        cur.execute("DELETE FROM parsed_documents WHERE file_name=?", (VENDOR_PDF.name,))
        for i, b in enumerate(blocks):
            doc_id = f"{VENDOR_ID}:{b['page']}:{i}"
            cur.execute(
                "INSERT OR REPLACE INTO parsed_documents "
                "(doc_id, file_name, page, bbox, text) VALUES (?, ?, ?, ?, ?)",
                (doc_id, VENDOR_PDF.name, b["page"], str(b["bbox"]), b["text"]),
            )
        conn.commit()

    print(f"  → {len(blocks)} blocks available for retrieval")

    # ── Step 3: evaluate each NB01 spec against the PDF ──────────────────────
    print(f"\n{_BOLD}[3/4] Evaluating {len(nb01_specs)} specs × 1 vendor{_RESET}")
    model_name   = default_model()
    vendor_index = VendorIndex.build(blocks)

    # clear any previous results for this vendor+sheet combo
    spec_ids = [s.get("Spec_ID", "") for s in nb01_specs]
    if spec_ids:
        placeholders = ",".join("?" * len(spec_ids))
        cur.execute(
            f"DELETE FROM compliance_matrix WHERE vendor_id=? AND spec_id IN ({placeholders})",
            [VENDOR_ID] + spec_ids,
        )
        conn.commit()

    results = []
    for idx, spec in enumerate(nb01_specs, start=1):
        spec_id   = spec.get("Spec_ID", "")
        param     = spec.get("Parameter_Name", "")
        req       = spec.get("company_Requirement") or spec.get("company_requirement", "")

        result = dispatch_spec_vendor(
            spec,
            VENDOR_ID,
            blocks,
            vendor_index=vendor_index,
            model_name=model_name,
            top_k=int(os.environ.get("FAST_TOP_K", "5")),
        )

        # persist to compliance_matrix
        citation_bbox = result.get("citation_bbox")
        if citation_bbox is not None:
            citation_bbox = json.dumps(citation_bbox)
        top_blocks = result.get("top_blocks", [])
        citation_doc_id = (
            f"{VENDOR_ID}:{top_blocks[0]['page']}:0" if top_blocks else None
        )

        cur.execute(
            "INSERT OR REPLACE INTO compliance_matrix "
            "(spec_id, vendor_id, status, citation, citation_doc_id, "
            " citation_excerpt, citation_page, citation_bbox, reasoning, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result["spec_id"],
                result["vendor_id"],
                result["status"],
                result["citation"],
                citation_doc_id,
                result["citation"][:1000],
                result.get("citation_page"),
                citation_bbox,
                result["reasoning"],
                result["confidence"],
            ),
        )
        conn.commit()

        results.append({
            "row":        idx,
            "spec_id":    spec_id,
            "parameter":  param,
            "requirement": req,
            "status":     result["status"],
            "confidence": result["confidence"],
            "citation":   result["citation"],
            "page":       result.get("citation_page"),
            "reasoning":  result["reasoning"],
        })

        status_str = _colour(result["status"])
        conf_str   = f"{result['confidence']:.2f}"
        print(
            f"  [{idx:>2}/{len(nb01_specs)}] {spec_id:<12} "
            f"{param[:22]:<22} → {status_str:<20} conf={conf_str}  "
            f"pg={result.get('citation_page') or '-'}"
        )

    # ── Step 4: build Excel report ────────────────────────────────────────────
    print(f"\n{_BOLD}[4/4] Building Excel report{_RESET}")
    timestamp    = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    history_tag  = f"{timestamp}_{run_id[:8]}"
    out_path     = OUTPUT_DIR / f"test_nb01_product_pdf_{history_tag}.xlsx"

    build_excel_report(str(out_path), db_path=str(DB_PATH), history_tag=history_tag)

    # mark run complete
    cur.execute(
        "UPDATE pipeline_runs SET status='completed', progress=100, "
        "message='NB01 test completed', updated_at=CURRENT_TIMESTAMP "
        "WHERE run_id=?",
        (run_id,),
    )
    conn.commit()
    conn.close()

    # ── Summary table ─────────────────────────────────────────────────────────
    yes_count      = sum(1 for r in results if r["status"].upper().startswith("YES"))
    nearly_count   = sum(1 for r in results if r["status"].upper().startswith("NEARLY"))
    no_count       = sum(1 for r in results if r["status"].upper().startswith("NO"))
    score_pct      = round((yes_count * 2 + nearly_count) / max(1, len(results) * 2) * 100, 1)

    print(f"\n{'='*70}")
    print(f"{_BOLD}RESULTS SUMMARY — NB01 × product-pdf{_RESET}")
    print(f"{'='*70}")
    print(f"  Total specs evaluated : {len(results)}")
    print(f"  {_GREEN}YES{_RESET}                   : {yes_count}")
    print(f"  {_YELLOW}NEARLY OK{_RESET}             : {nearly_count}")
    print(f"  {_RED}NO{_RESET}                    : {no_count}")
    print(f"  Compliance score      : {score_pct}%")
    print(f"{'='*70}")

    print(f"\n{_BOLD}Detailed results:{_RESET}")
    print(f"{'#':<4} {'Spec ID':<14} {'Parameter':<24} {'Status':<12} {'Conf':>5}  {'Citation (truncated)'}")
    print("-" * 100)
    for r in results:
        print(
            f"{r['row']:<4} {r['spec_id']:<14} {r['parameter'][:23]:<24} "
            f"{_colour(r['status']):<20} {r['confidence']:>5.2f}  "
            f"{_truncate(r['citation'], 60)}"
        )

    print(f"\n{_BOLD}Output files:{_RESET}")
    print(f"  Matrix report : {out_path}")
    vendor_file = OUTPUT_DIR / f"vendor_{VENDOR_ID}_{history_tag}.xlsx"
    if vendor_file.exists():
        print(f"  Vendor file   : {vendor_file}")
    print(f"  Database      : {DB_PATH}")
    print(f"  Run ID        : {run_id}")
    print()


if __name__ == "__main__":
    main()
