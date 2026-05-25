from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

import pandas as pd


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _normalize(text: str) -> str:
    return _clean(text).lower()


def _find_header_row(df: pd.DataFrame) -> Optional[int]:
    max_rows = min(15, len(df))
    for idx in range(max_rows):
        row = [_normalize(df.iloc[idx, c]) for c in range(min(10, len(df.columns)))]
        if any(val in {"s. no.", "s.no.", "s no.", "s.no", "s no"} for val in row) and any("parameter" in val for val in row):
            return idx
        if any("parameter" in val for val in row) and any("spec" in val or "requirement" in val or "detail" in val for val in row):
            return idx
    return None


def _detect_columns(header_row: List[str]) -> Tuple[int, int, int]:
    serial_col = None
    param_col = None
    req_col = None
    for idx, val in enumerate(header_row):
        if serial_col is None and (val in {"s. no.", "s.no.", "s no.", "s.no", "s no", "s.no"} or "spec_id" in val):
            serial_col = idx
        if param_col is None and "parameter" in val:
            param_col = idx
        if req_col is None and ("requirement" in val or "specification" in val or "detail" in val):
            req_col = idx
    if req_col is None:
        for idx, val in enumerate(header_row):
            if "spec" in val and idx != serial_col:
                req_col = idx
                break
    serial_col = serial_col if serial_col is not None else 0
    param_col = param_col if param_col is not None else min(1, len(header_row) - 1)
    req_col = req_col if req_col is not None else min(2, len(header_row) - 1)
    return serial_col, param_col, req_col


def _parse_workbook(excel_path: str) -> List[Dict]:
    records: List[Dict] = []
    workbook = pd.ExcelFile(excel_path)

    for sheet_name in workbook.sheet_names:
        df = pd.read_excel(workbook, sheet_name=sheet_name, header=None, dtype=str).fillna("")
        if df.empty or len(df.columns) < 3:
            continue

        item_name = _clean(df.iloc[0, 2]) if len(df) > 0 and len(df.columns) > 2 else ""
        raw_code = _clean(df.iloc[1, 2]) if len(df) > 1 and len(df.columns) > 2 else ""
        item_code = ""
        if raw_code and re.match(r"^[A-Z]{1,5}\d{1,5}$", raw_code.strip()):
            item_code = raw_code.strip()

        header_row = _find_header_row(df)
        start_row = (header_row + 1) if header_row is not None else 3
        header_vals = [_normalize(df.iloc[header_row, c]) for c in range(len(df.columns))] if header_row is not None else []
        serial_col, param_col, req_col = _detect_columns(header_vals) if header_vals else (0, 1, 2)

        last_serial = ""
        last_param = ""
        row_counter = 0
        for row_idx in range(start_row, len(df)):
            serial_no = _clean(df.iloc[row_idx, serial_col]) if len(df.columns) > serial_col else ""
            parameter_name = _clean(df.iloc[row_idx, param_col]) if len(df.columns) > param_col else ""
            requirement = _clean(df.iloc[row_idx, req_col]) if len(df.columns) > req_col else ""

            if not any([serial_no, parameter_name, requirement]):
                continue

            if serial_no.lower() in {"s. no.", "s.no.", "s no.", "s.no", "s no", "s.no"}:
                continue

            if serial_no:
                last_serial = serial_no
            else:
                serial_no = last_serial

            if parameter_name:
                last_param = parameter_name
            else:
                parameter_name = last_param

            spec_suffix = serial_no or f"{row_idx + 1}"
            if serial_no and re.search(r"[A-Za-z]", serial_no):
                spec_id = serial_no
            elif item_code:
                spec_id = f"{item_code}-{spec_suffix}"
            else:
                spec_id = f"{sheet_name}-{spec_suffix}"
            if item_name and parameter_name and not parameter_name.startswith(item_name):
                parameter_name = f"{item_name} - {parameter_name}"

            row_counter += 1
            row_index = None
            if serial_no and str(serial_no).strip().isdigit():
                row_index = int(str(serial_no).strip())
            else:
                row_index = row_counter

            records.append(
                {
                    "Spec_ID": spec_id,
                    "Parameter_Name": parameter_name,
                    "company_Requirement": requirement,
                    "sheet_name": sheet_name,
                    "row_index": row_index,
                }
            )

    return records


def parse_master_excel(excel_path: str) -> List[Dict]:
    """Load master spec checklist from Excel.

    Supports multi-sheet company checklists and a simplified single-sheet format.
    Returns list of dicts.
    """
    return _parse_workbook(excel_path)
