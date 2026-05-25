from pathlib import Path
import logging
import json
import uuid
from datetime import datetime
from typing import Callable, Optional
from src.ingest.excel_parser import parse_master_excel
from src.ingest.pdf_parser import parse_pdf_blocks
from src.storage.db import init_db, get_connection
from src.engine.orchestrator import dispatch_spec_vendor
from src.reporting.excel_report import build_excel_report
from src.utils.logging import setup_logging
from src.utils.paths import PROJECT_ROOT


def _pick_master_workbook(cfg_in: Path) -> Path | None:
    preferred = cfg_in / "Tech_Comp_check_list.xlsx"
    if preferred.exists():
        return preferred
    candidates = sorted(
        path for path in cfg_in.glob("*.xlsx") if path.name.lower() != "tech_comp_check_list.xlsx"
    )
    return candidates[0] if candidates else None


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

    # locate master spec
    master = _pick_master_workbook(cfg_in)
    if master is None:
        logging.error("No master spec .xlsx found in data/incoming")
        return
    specs = parse_master_excel(str(master))

    # locate vendor pdfs
    vendor_files = list(cfg_in.glob("*.pdf"))
    if not vendor_files:
        logging.error("No vendor PDFs found in data/incoming")
        return

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
    for index, spec in enumerate(specs, start=1):
        cur.execute(
            "INSERT OR REPLACE INTO master_specs (source_file, sheet_name, spec_id, parameter_name, company_requirement, row_index) VALUES (?, ?, ?, ?, ?, ?)",
            (
                master.name,
                spec.get("sheet_name", ""),
                spec.get("Spec_ID", ""),
                spec.get("Parameter_Name", ""),
                spec.get("company_Requirement", spec.get("company_Requirement", spec.get("company_requirement", ""))),
                spec.get("row_index", index),
            ),
        )
    conn.commit()

    existing_pairs = set(
        cur.execute("SELECT spec_id, vendor_id FROM compliance_matrix").fetchall()
    )

    total_pairs = max(1, len(vendor_files) * len(specs))
    processed_pairs = 0

    try:
        for v in vendor_files:
            vendor_id = v.stem
            logging.info(f"Parsing vendor file: {v.name}")
            blocks = parse_pdf_blocks(str(v))

            cur.execute(
                "INSERT OR REPLACE INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
                ("parse_pdf", "vendor", vendor_id, json.dumps({"file": v.name, "pages": len(blocks)})),
            )

            for i, b in enumerate(blocks):
                doc_id = f"{vendor_id}:{b['page']}:{i}"
                cur.execute(
                    "INSERT OR REPLACE INTO parsed_documents (doc_id, file_name, page, bbox, text) VALUES (?, ?, ?, ?, ?)",
                    (doc_id, v.name, b["page"], str(b["bbox"]), b["text"]),
                )

            for spec in specs:
                spec_id = spec.get("Spec_ID", "")
                if (spec_id, vendor_id) in existing_pairs:
                    processed_pairs += 1
                    progress = round((processed_pairs / total_pairs) * 100, 2)
                    message = f"Skipped {processed_pairs}/{total_pairs} pairs (already processed)"
                    cur.execute(
                        "UPDATE pipeline_runs SET progress=?, message=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                        (progress, message, run_id),
                    )
                    if progress_cb:
                        progress_cb(progress, message)
                    continue

                result = dispatch_spec_vendor(spec, vendor_id, blocks)
                citation_bbox = result.get("citation_bbox")
                if citation_bbox is not None:
                    citation_bbox = json.dumps(citation_bbox)
                cur.execute(
                    "INSERT OR REPLACE INTO compliance_matrix (spec_id, vendor_id, status, citation, citation_doc_id, citation_excerpt, citation_page, citation_bbox, reasoning, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result["spec_id"],
                        result["vendor_id"],
                        result["status"],
                        result["citation"],
                        result.get("top_blocks", [{}])[0].get("page") and f"{vendor_id}:{result.get('top_blocks', [{}])[0].get('page')}:0",
                        result["citation"][:1000],
                        result.get("citation_page"),
                        citation_bbox,
                        result["reasoning"],
                        result["confidence"],
                    ),
                )
                processed_pairs += 1
                progress = round((processed_pairs / total_pairs) * 100, 2)
                message = f"Processed {processed_pairs}/{total_pairs} pairs"
                cur.execute(
                    "UPDATE pipeline_runs SET progress=?, message=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                    (progress, message, run_id),
                )
                if progress_cb:
                    progress_cb(progress, message)

            conn.commit()

        cur.execute(
            "UPDATE pipeline_runs SET status=?, progress=?, message=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            ("completed", 100.0, "Pipeline completed", run_id),
        )
        cur.execute(
            "INSERT INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
            ("pipeline_complete", "run", run_id, json.dumps({"output": str(cfg_out / 'vendor_comparison_matrix.xlsx')})),
        )
        conn.commit()
    except Exception as exc:
        cur.execute(
            "UPDATE pipeline_runs SET status=?, error=?, message=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            ("failed", str(exc), "Pipeline failed", run_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()

    # build report
    out_path = cfg_out / "vendor_comparison_matrix.xlsx"
    build_excel_report(str(out_path), db_path=str(cfg_db))
    logging.info(f"Report written to {out_path}")


if __name__ == "__main__":
    main()
