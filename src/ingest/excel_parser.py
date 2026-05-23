from pathlib import Path
from typing import List, Dict

import pandas as pd


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _parse_tech_checklist(excel_path: str) -> List[Dict]:
    records: List[Dict] = []
    workbook = pd.ExcelFile(excel_path)

    for sheet_name in workbook.sheet_names:
        df = pd.read_excel(workbook, sheet_name=sheet_name, header=None, dtype=str).fillna("")
        if df.empty or len(df.columns) < 3:
            continue

        item_code = _clean(df.iloc[1, 2]) if len(df) > 1 and len(df.columns) > 2 else ""
        item_name = _clean(df.iloc[0, 2]) if len(df) > 0 and len(df.columns) > 2 else ""

        header_row = None
        for idx in range(len(df)):
            first_cell = _clean(df.iloc[idx, 0]).lower()
            second_cell = _clean(df.iloc[idx, 1]).lower() if len(df.columns) > 1 else ""
            if first_cell in {"s. no.", "s.no.", "s no.", "s.no", "s no"} and "parameter" in second_cell:
                header_row = idx
                break

        start_row = (header_row + 1) if header_row is not None else 3
        for row_idx in range(start_row, len(df)):
            serial_no = _clean(df.iloc[row_idx, 0]) if len(df.columns) > 0 else ""
            parameter_name = _clean(df.iloc[row_idx, 1]) if len(df.columns) > 1 else ""
            requirement = _clean(df.iloc[row_idx, 2]) if len(df.columns) > 2 else ""

            if not any([serial_no, parameter_name, requirement]):
                continue
            if serial_no.lower() in {"s. no.", "s.no.", "s no.", "s.no", "s no"}:
                continue

            spec_id = f"{item_code}-{serial_no}" if item_code and serial_no else serial_no or f"{sheet_name}-{row_idx + 1}"
            if item_name and parameter_name:
                parameter_name = f"{item_name} - {parameter_name}"

            records.append(
                {
                    "Spec_ID": spec_id,
                    "Parameter_Name": parameter_name,
                    "BHEL_Requirement": requirement,
                    "company_Requirement": requirement,
                }
            )

    return records


def parse_master_excel(excel_path: str) -> List[Dict]:
    """Load master spec checklist from Excel.

    Expects columns: Spec_ID, Parameter_Name, BHEL_Requirement (case-insensitive).
    Returns list of dicts.
    """
    if Path(excel_path).name.lower() == "tech_comp_check_list.xlsx":
        return _parse_tech_checklist(excel_path)

    df = pd.read_excel(excel_path, dtype=str)
    # Normalize column names
    cols = {c.lower(): c for c in df.columns}
    def get(col):
        return df[cols[col]] if col in cols else None

    # Try several common names
    spec_col = cols.get("spec_id") or cols.get("spec") or list(df.columns)[0]
    name_col = cols.get("parameter_name") or cols.get("parameter") or list(df.columns)[1]
    req_col = cols.get("bhel_requirement") or cols.get("company_requirement") or cols.get("requirement") or list(df.columns)[2]

    records = []
    for _, row in df.iterrows():
        requirement = str(row[req_col])
        records.append({
            "Spec_ID": str(row[spec_col]),
            "Parameter_Name": str(row[name_col]),
            "BHEL_Requirement": requirement,
            "company_Requirement": requirement,
        })
    return records
