from pathlib import Path
import logging
from src.ingest.excel_parser import parse_master_excel
from src.ingest.pdf_parser import parse_pdf_blocks
from src.storage.db import init_db, get_connection
from src.evaluator import MultiAgentEvaluator
from src.reporting.excel_report import build_excel_report
from src.utils.logging import setup_logging
from src.utils.paths import PROJECT_ROOT


def main() -> None:
    setup_logging()
    logging.info("Starting pipeline")

    cfg_in = PROJECT_ROOT / "data" / "incoming"
    cfg_parsed = PROJECT_ROOT / "data" / "parsed"
    cfg_out = PROJECT_ROOT / "data" / "output"
    cfg_db = cfg_parsed / "app.db"

    cfg_parsed.mkdir(parents=True, exist_ok=True)
    cfg_out.mkdir(parents=True, exist_ok=True)

    init_db(str(cfg_db))

    # locate master spec
    master_candidates = list(cfg_in.glob("*.xlsx"))
    if not master_candidates:
        logging.error("No master spec .xlsx found in data/incoming")
        return
    master = master_candidates[0]
    specs = parse_master_excel(str(master))

    # locate vendor pdfs
    vendor_files = list(cfg_in.glob("*.pdf"))
    if not vendor_files:
        logging.error("No vendor PDFs found in data/incoming")
        return

    evaluator = MultiAgentEvaluator()

    # Simple parse and evaluate loop with richer citation metadata
    conn = get_connection(str(cfg_db))
    cur = conn.cursor()

    for v in vendor_files:
        vendor_id = v.stem
        logging.info(f"Parsing vendor file: {v.name}")
        blocks = parse_pdf_blocks(str(v))

        # persist parsed blocks and build a mapping from doc_id -> block
        block_map = {}
        for i, b in enumerate(blocks):
            doc_id = f"{vendor_id}:{b['page']}:{i}"
            block_map[doc_id] = b
            cur.execute(
                "INSERT OR REPLACE INTO parsed_documents (doc_id, file_name, page, bbox, text) VALUES (?, ?, ?, ?, ?)",
                (doc_id, v.name, b["page"], str(b["bbox"]), b["text"]),
            )

        # Evaluate per-spec by scanning blocks and choosing best result
        for spec in specs:
            best = None
            # evaluate each block individually so the evaluator can cite exact snippet
            for doc_id, b in block_map.items():
                res = evaluator.evaluate_spec(vendor_id, spec, b["text"])
                # attach block reference to result temporarily
                candidate = (res, doc_id)
                if best is None or res.confidence > best[0].confidence:
                    best = candidate

            if best is None:
                # no blocks? store a NO result
                cur.execute(
                    "INSERT OR REPLACE INTO compliance_matrix (spec_id, vendor_id, status, citation, reasoning, confidence, citation_doc_id, citation_excerpt) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (spec["Spec_ID"], vendor_id, "NO", "", "No context available", 0.0, None, None),
                )
            else:
                res, doc_id = best
                excerpt = res.citation or (block_map[doc_id]["text"][:800])
                cur.execute(
                    "INSERT OR REPLACE INTO compliance_matrix (spec_id, vendor_id, status, citation, reasoning, confidence, citation_doc_id, citation_excerpt) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (spec["Spec_ID"], vendor_id, res.status, excerpt, res.reasoning, res.confidence, doc_id, excerpt[:1000]),
                )

        conn.commit()

    conn.close()

    # build report
    out_path = cfg_out / "vendor_comparison_matrix.xlsx"
    build_excel_report(str(out_path))
    logging.info(f"Report written to {out_path}")


if __name__ == "__main__":
    main()
