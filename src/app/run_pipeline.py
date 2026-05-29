from pathlib import Path
import logging
import json
import os
import shutil
import uuid
import traceback
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional
from src.ingest.excel_parser import parse_master_excel
from src.ingest.pdf_parser import parse_pdf_blocks
from src.storage.db import init_db, get_connection
from src.engine.ollama_client import default_model
from src.engine.orchestrator import VendorIndex, dispatch_spec_vendor, get_dispatch_stats, reset_dispatch_stats
from src.reporting.excel_report import build_excel_report
from src.utils.logging import setup_logging
from src.utils.paths import PROJECT_ROOT
from src.evaluator import retrain_from_feedback


def _load_blocks_from_db(cur, file_name: str) -> list[dict]:
    rows = cur.execute(
        "SELECT doc_id, page, bbox, text FROM parsed_documents WHERE file_name=? ORDER BY page, doc_id",
        (file_name,),
    ).fetchall()
    blocks = []
    for doc_id, page, bbox, text in rows:
        try:
            parsed_bbox = json.loads(bbox)
        except Exception:
            parsed_bbox = bbox
        blocks.append({"doc_id": doc_id, "page": page, "bbox": parsed_bbox, "text": text})
    return blocks


def _citation_doc_id(vendor_id: str, top_blocks: list[dict]) -> str | None:
    if not top_blocks:
        return None
    doc_id = top_blocks[0].get("doc_id")
    if isinstance(doc_id, str) and doc_id:
        return doc_id
    page = top_blocks[0].get("page")
    return f"{vendor_id}:{page}:0" if page is not None else None


def _pick_master_workbook(cfg_in: Path) -> Path | None:
    # Prefer the most recently modified Tech_Comp_check_list variant first,
    # then fall back to any other .xlsx in the directory.
    tech_variants = sorted(
        cfg_in.glob("Tech_Comp_check_list*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,   # newest first
    )
    if tech_variants:
        return tech_variants[0]
    candidates = sorted(
        path for path in cfg_in.glob("*.xlsx")
        if not path.name.lower().startswith("tech_comp_check_list")
    )
    return candidates[0] if candidates else None


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int = 0) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _bounded_workers(name: str, default: int, upper: int) -> int:
    configured = _int_env(name, default)
    if configured <= 0:
        configured = default
    return max(1, min(configured, max(1, upper)))


def _update_progress(cur, conn, run_id: str, progress: float, message: str, progress_cb=None) -> None:
    """Write progress to DB and commit immediately so the API can read it."""
    cur.execute(
        "UPDATE pipeline_runs SET progress=?, message=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
        (round(progress, 2), message, run_id),
    )
    conn.commit()
    if progress_cb:
        progress_cb(round(progress, 2), message)


def main(run_id: str | None = None, progress_cb: Optional[Callable[[float, str], None]] = None) -> None:
    setup_logging()
    logging.info("Starting pipeline")

    cfg_in = PROJECT_ROOT / "data" / "incoming"
    cfg_parsed = PROJECT_ROOT / "data" / "parsed"
    cfg_out = PROJECT_ROOT / "data" / "output"
    cfg_db = cfg_parsed / "app.db"

    cfg_parsed.mkdir(parents=True, exist_ok=True)
    cfg_out.mkdir(parents=True, exist_ok=True)

    init_db(str(cfg_db))
    run_id = run_id or str(uuid.uuid4())

    # â”€â”€ Auto-retrain from any pending human feedback before this run â”€â”€â”€â”€â”€â”€â”€â”€â”€
    pending = get_connection(str(cfg_db)).execute(
        "SELECT COUNT(*) FROM training_queue WHERE processed=0"
    ).fetchone()[0]
    if pending:
        new_rules = retrain_from_feedback(db_path=str(cfg_db))
        logging.info("Auto-retrain: %d new rules from %d pending feedback items", new_rules, pending)

    # locate master spec â€” pass db_conn so format profiles are cached/learned
    master = _pick_master_workbook(cfg_in)
    if master is None:
        logging.error("No master spec .xlsx found in data/incoming")
        return
    conn_for_profile = get_connection(str(cfg_db))
    try:
        specs = parse_master_excel(str(master), db_conn=conn_for_profile)
    except TypeError:
        # monkeypatched or older version that doesn't accept db_conn
        specs = parse_master_excel(str(master))
    finally:
        conn_for_profile.close()

    # ── Optional sheet filter: PIPELINE_SHEET_FILTER=NB01,PC01 ──────────────
    _sheet_filter_raw = os.environ.get("PIPELINE_SHEET_FILTER", "").strip()
    if _sheet_filter_raw:
        _allowed_sheets = {s.strip() for s in _sheet_filter_raw.split(",") if s.strip()}
        before = len(specs)
        specs = [s for s in specs if s.get("sheet_name", "") in _allowed_sheets]
        logging.info(
            "PIPELINE_SHEET_FILTER=%s: kept %d/%d specs",
            _sheet_filter_raw, len(specs), before,
        )

    fast_mode = _bool_env("FAST_MODE")
    if fast_mode:
        os.environ.setdefault("FAST_SKIP_OCR", "1")
        os.environ.setdefault("FAST_PDF_PAGES", "10")
        os.environ.setdefault("FAST_SPEC_LIMIT", "25")
        os.environ.setdefault("FAST_TOP_K", "3")
        os.environ.setdefault("FAST_VENDOR_LIMIT", "1")
        os.environ.setdefault("FAST_BLOCK_LIMIT", "300")
        os.environ.setdefault("FAST_REUSE_PARSED", "1")

    spec_limit = _int_env("FAST_SPEC_LIMIT", 0)
    if spec_limit and len(specs) > spec_limit:
        specs = specs[:spec_limit]
        logging.info("Limiting specs to %s", spec_limit)

    top_k = _int_env("FAST_TOP_K", 3 if fast_mode else 2)
    cpu = os.cpu_count() or 2
    eval_workers = _bounded_workers(
        "PIPELINE_EVAL_WORKERS",
        min(8, cpu * 2) if fast_mode else min(6, max(4, cpu)),
        16,
    )
    model_name = default_model()
    reset_dispatch_stats()

    # locate vendor pdfs
    vendor_files = list(cfg_in.glob("*.pdf"))
    if not vendor_files:
        logging.error("No vendor PDFs found in data/incoming")
        return

    # ── Optional vendor filter: PIPELINE_VENDOR_FILTER=product-pdf,vendorB ──
    _vendor_filter_raw = os.environ.get("PIPELINE_VENDOR_FILTER", "").strip()
    if _vendor_filter_raw:
        _allowed_vendors = {v.strip() for v in _vendor_filter_raw.split(",") if v.strip()}
        before = len(vendor_files)
        vendor_files = [v for v in vendor_files if v.stem in _allowed_vendors]
        logging.info(
            "PIPELINE_VENDOR_FILTER=%s: kept %d/%d PDFs",
            _vendor_filter_raw, len(vendor_files), before,
        )
        if not vendor_files:
            logging.error("No vendor PDFs remain after PIPELINE_VENDOR_FILTER — check PDF stem names")
            return

    vendor_limit = _int_env("FAST_VENDOR_LIMIT", 0)
    if vendor_limit and len(vendor_files) > vendor_limit:
        vendor_files = vendor_files[:vendor_limit]
        logging.info("Limiting vendors to %s", vendor_limit)

    n_vendors = len(vendor_files)
    n_specs = len(specs)

    # Phase weights: parsing = 20%, evaluation = 70%, report = 10%
    PARSE_WEIGHT = 20.0
    EVAL_WEIGHT = 70.0
    # REPORT_WEIGHT = 10.0  (remainder)

    conn = get_connection(str(cfg_db))
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO pipeline_runs (run_id, status, progress, message, error, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (run_id, "running", 0.0, "Pipeline started", ""),
    )
    cur.execute(
        "INSERT INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
        ("pipeline_start", "run", run_id, json.dumps({"master": master.name, "vendors": [v.name for v in vendor_files]})),
    )
    cur.execute("DELETE FROM master_specs WHERE source_file=?", (master.name,))
    for index, spec in enumerate(specs, start=1):
        cur.execute(
            "INSERT OR REPLACE INTO master_specs (source_file, sheet_name, spec_id, parameter_name, company_requirement, row_index) VALUES (?, ?, ?, ?, ?, ?)",
            (
                master.name,
                spec.get("sheet_name", ""),
                spec.get("Spec_ID", ""),
                spec.get("Parameter_Name", ""),
                spec.get("company_Requirement") or spec.get("company_requirement", ""),
                spec.get("row_index", index),
            ),
        )
    conn.commit()
    _update_progress(cur, conn, run_id, 1.0, f"Loaded {n_specs} specs, {n_vendors} vendor PDFs", progress_cb)

    existing_pairs = set(
        cur.execute("SELECT spec_id, vendor_id FROM compliance_matrix").fetchall()
    )

    total_pairs = max(1, n_vendors * n_specs)
    processed_pairs = 0

    try:
        # â”€â”€ Phase 1: Parse all vendor PDFs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        parsed_blocks: dict[str, list[dict]] = {}
        for v_idx, v in enumerate(vendor_files):
            vendor_id = v.stem
            parse_start_pct = PARSE_WEIGHT * (v_idx / n_vendors)
            parse_end_pct   = PARSE_WEIGHT * ((v_idx + 1) / n_vendors)

            _update_progress(
                cur, conn, run_id,
                parse_start_pct,
                f"Parsing PDF {v_idx + 1}/{n_vendors}: {v.name}",
                progress_cb,
            )
            logging.info(f"Parsing vendor file: {v.name}")

            reuse_parsed = _bool_env("FAST_REUSE_PARSED")
            db_blocks = None
            if reuse_parsed:
                existing_count = cur.execute(
                    "SELECT COUNT(*) FROM parsed_documents WHERE file_name=?",
                    (v.name,),
                ).fetchone()[0]
                if existing_count:
                    db_blocks = _load_blocks_from_db(cur, v.name)
                    logging.info("Reusing %s parsed blocks for %s", len(db_blocks), v.name)
                    cur.execute(
                        "INSERT OR REPLACE INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
                        ("parse_pdf", "vendor", vendor_id, json.dumps({"file": v.name, "pages": len(db_blocks), "reused": True})),
                    )

            if db_blocks is None:
                blocks = parse_pdf_blocks(str(v))
                cur.execute(
                    "INSERT OR REPLACE INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
                    ("parse_pdf", "vendor", vendor_id, json.dumps({"file": v.name, "pages": len(blocks)})),
                )
                for i, b in enumerate(blocks):
                    doc_id = f"{vendor_id}:{b['page']}:{i}"
                    b["doc_id"] = doc_id
                    cur.execute(
                        "INSERT OR REPLACE INTO parsed_documents (doc_id, file_name, page, bbox, text) VALUES (?, ?, ?, ?, ?)",
                        (doc_id, v.name, b["page"], str(b["bbox"]), b["text"]),
                    )
                db_blocks = blocks

            block_limit = _int_env("FAST_BLOCK_LIMIT", 0)
            if block_limit and len(db_blocks) > block_limit:
                db_blocks = db_blocks[:block_limit]

            parsed_blocks[vendor_id] = db_blocks
            _update_progress(
                cur, conn, run_id,
                parse_end_pct,
                f"Parsed {v.name} â€” {len(db_blocks)} blocks",
                progress_cb,
            )

        # â”€â”€ Phase 2: Evaluate spec/vendor pairs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        vendor_indexes = {
            vendor_id: VendorIndex.build(blocks)
            for vendor_id, blocks in parsed_blocks.items()
        }
        pending_tasks = []
        for v_idx, v in enumerate(vendor_files):
            vendor_id = v.stem
            db_blocks = parsed_blocks[vendor_id]
            vendor_index = vendor_indexes[vendor_id]

            for s_idx, spec in enumerate(specs):
                spec_id = spec.get("Spec_ID", "")
                pair_idx = v_idx * n_specs + s_idx

                if (spec_id, vendor_id) in existing_pairs:
                    processed_pairs += 1
                    _update_progress(
                        cur, conn, run_id,
                        PARSE_WEIGHT + EVAL_WEIGHT * (processed_pairs / total_pairs),
                        f"Skipped {processed_pairs}/{total_pairs} pairs (cached)",
                        progress_cb,
                    )
                    continue

                pending_tasks.append((pair_idx, spec, vendor_id, db_blocks, vendor_index))

        llm_concurrent = _int_env("LLM_MAX_CONCURRENT", 2)
        _update_progress(
            cur, conn, run_id,
            PARSE_WEIGHT + EVAL_WEIGHT * (processed_pairs / total_pairs),
            f"Evaluating {len(pending_tasks)} pairs — {eval_workers} workers, max {llm_concurrent} LLM calls",
            progress_cb,
        )
        logging.info(
            "Eval config: workers=%s top_k=%s model=%s llm_only_uncertain=%s",
            eval_workers,
            top_k,
            model_name,
            _bool_env("LLM_ONLY_UNCERTAIN"),
        )

        def _evaluate_task(task):
            pair_idx, spec, vendor_id, db_blocks, vendor_index = task
            result = dispatch_spec_vendor(
                spec,
                vendor_id,
                db_blocks,
                vendor_index=vendor_index,
                model_name=model_name,
                top_k=top_k,
                fast=fast_mode,
            )
            return pair_idx, vendor_id, spec.get("Spec_ID", ""), result

        with ThreadPoolExecutor(max_workers=eval_workers) as executor:
            future_map = {executor.submit(_evaluate_task, task): task for task in pending_tasks}
            for future in as_completed(future_map):
                pair_idx, vendor_id, spec_id, result = future.result()
                citation_bbox = result.get("citation_bbox")
                if citation_bbox is not None:
                    citation_bbox = json.dumps(citation_bbox)
                top_blocks = result.get("top_blocks", [])
                cur.execute(
                    "INSERT OR REPLACE INTO compliance_matrix (spec_id, vendor_id, status, citation, citation_doc_id, citation_excerpt, citation_page, citation_bbox, reasoning, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result["spec_id"],
                        result["vendor_id"],
                        result["status"],
                        result["citation"],
                        _citation_doc_id(vendor_id, top_blocks),
                        result["citation"][:1000],
                        result.get("citation_page"),
                        citation_bbox,
                        result["reasoning"],
                        result["confidence"],
                    ),
                )
                processed_pairs += 1
                if processed_pairs == 1 or processed_pairs % 25 == 0:
                    logging.info(
                        "Progress %s/%s — last %s x %s -> %s",
                        processed_pairs,
                        total_pairs,
                        vendor_id,
                        spec_id,
                        result["status"],
                    )
                _update_progress(
                    cur, conn, run_id,
                    PARSE_WEIGHT + EVAL_WEIGHT * (processed_pairs / total_pairs),
                    f"Evaluated {processed_pairs}/{total_pairs} pairs - {vendor_id} x {spec_id} -> {result['status']}",
                    progress_cb,
                )

        stats = get_dispatch_stats()
        logging.info("Dispatch stats: %s", stats)

        # â”€â”€ Phase 3: Build report â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        history_tag = f"{timestamp}_{run_id[:8]}"
        _update_progress(cur, conn, run_id, 91.0, "Building Excel reportâ€¦", progress_cb)
        cur.execute(
            "INSERT INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
            ("pipeline_complete", "run", run_id, json.dumps({"history_tag": history_tag})),
        )
        conn.commit()

    except Exception:
        error_details = traceback.format_exc()
        logging.exception("Pipeline failed")
        cur.execute(
            "UPDATE pipeline_runs SET status=?, error=?, message=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            ("failed", error_details, "Pipeline failed", run_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()

    # build report (outside the connection so it doesn't hold the lock)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    history_tag = f"{timestamp}_{run_id[:8]}"
    out_path = cfg_out / f"vendor_comparison_matrix_{history_tag}.xlsx"
    build_excel_report(str(out_path), db_path=str(cfg_db), history_tag=history_tag)
    latest_path = cfg_out / "vendor_comparison_matrix.xlsx"
    shutil.copy2(out_path, latest_path)
    logging.info(f"Report written to {out_path} and latest copy to {latest_path}")

    # final status update
    conn2 = get_connection(str(cfg_db))
    try:
        conn2.execute(
            "UPDATE pipeline_runs SET status=?, progress=?, message=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            ("completed", 100.0, "Pipeline completed", run_id),
        )
        conn2.commit()
    finally:
        conn2.close()
    if progress_cb:
        progress_cb(100.0, "Pipeline completed")
