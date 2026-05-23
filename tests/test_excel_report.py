import sqlite3
from pathlib import Path

import openpyxl

from src.reporting.excel_report import build_excel_report
from src.storage.db import init_db


def test_build_excel_report_writes_three_sheets_and_colors(tmp_path):
    db_path = tmp_path / "app.db"
    output_path = tmp_path / "vendor_comparison_matrix.xlsx"
    init_db(str(db_path))

    conn = sqlite3.connect(str(db_path))
    conn.executemany(
        "INSERT INTO compliance_matrix (spec_id, vendor_id, status, citation, reasoning, confidence, citation_doc_id, citation_excerpt, citation_page, citation_bbox) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("SPEC-01", "VendorA", "YES", "citation a", "reason a", 0.9, "doc-1", "excerpt a", 1, "[0,0,10,10]"),
            ("SPEC-01", "VendorB", "NO", "citation b", "reason b", 0.2, "doc-2", "excerpt b", 2, "[0,0,10,10]"),
        ],
    )
    conn.commit()
    conn.close()

    build_excel_report(str(output_path), db_path=str(db_path))

    wb = openpyxl.load_workbook(output_path)
    assert wb.sheetnames == ["Matrix", "Details", "Summary"]

    matrix = wb["Matrix"]
    assert matrix["B2"].value == "YES"
    assert matrix["C2"].value == "NO"
    assert matrix["B2"].fill.fgColor.rgb in {"00C6EFCE", "C6EFCE"}
    assert matrix["C2"].fill.fgColor.rgb in {"00FFC7CE", "FFC7CE"}

