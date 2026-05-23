from pathlib import Path

from openpyxl import Workbook

from src.ingest.excel_loader import load_master_spec, normalize_tech_checklist
from src.ingest.excel_parser import parse_master_excel


def _build_master_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Spec_ID", "Parameter_Name", "BHEL_Requirement"])
    ws.append(["SPEC-01", "Max Operating Temp", "Must withstand at least 600C continuously."])
    ws.append(["SPEC-02", "Hydrostatic Pressure", "Shell must withstand 60 bar total pressure."])
    wb.save(path)


def _build_checklist_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "UP01"
    ws.append(["Item Name", None, "Small UPS- 800 VA", "Vendor Response", None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None, None])
    ws.append(["Item Code", None, "UP01", "Dynacons", None, None, "Alstonia", None, None, None, None, None, None, None, None, None, None, None, None, None, None])
    ws.append(["S.No.", "Parameter / Feature", "Detailed Specifications", "Bidder's Compliance (Y/N)", "Remarks", "Page No. in Bid document", "Bidder's Compliance (Y/N)", "Remarks", "Page No. in Bid document", None, None, None, None, None, None, None, None, None, None, None, None])
    ws.append([1, "Make & Model", "UPS Model X", "Y", "Complies with spec", 12, "N", "Missing feature", 14, None, None, None, None, None, None, None, None, None, None, None, None])
    wb.save(path)


def test_parse_master_excel_returns_bhel_requirement_alias(tmp_path):
    workbook = tmp_path / "master.xlsx"
    _build_master_workbook(workbook)

    rows = parse_master_excel(str(workbook))

    assert len(rows) == 2
    assert rows[0]["Spec_ID"] == "SPEC-01"
    assert rows[0]["BHEL_Requirement"] == "Must withstand at least 600C continuously."
    assert rows[0]["company_Requirement"] == rows[0]["BHEL_Requirement"]


def test_load_master_spec_exact_columns(tmp_path):
    workbook = tmp_path / "master.xlsx"
    _build_master_workbook(workbook)

    rows = load_master_spec(str(workbook))

    assert len(rows) == 2
    assert rows[1]["Spec_ID"] == "SPEC-02"
    assert rows[1]["BHEL_Requirement"] == "Shell must withstand 60 bar total pressure."


def test_normalize_tech_checklist_expands_vendor_blocks(tmp_path):
    workbook = tmp_path / "checklist.xlsx"
    _build_checklist_workbook(workbook)

    rows = normalize_tech_checklist(str(workbook))

    assert len(rows) == 2
    assert rows[0]["sheet"] == "UP01"
    assert rows[0]["item_code"] == "UP01"
    assert rows[0]["product_label"] == "Small UPS- 800 VA"
    assert rows[0]["vendor_name"] == "Dynacons"
    assert rows[0]["serial_no"] == "1"
    assert rows[0]["compliance"] == "Y"
    assert rows[0]["remarks"] == "Complies with spec"
    assert rows[0]["page_no"] == "12"
    assert rows[1]["vendor_name"] == "Alstonia"
    assert rows[1]["compliance"] == "N"
    assert rows[1]["remarks"] == "Missing feature"
