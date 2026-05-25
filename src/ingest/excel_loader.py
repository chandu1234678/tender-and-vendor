from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


VENDOR_GROUP_STARTS = (3, 6, 9, 12, 15, 18)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _find_vendor_groups(df: pd.DataFrame) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    row0 = df.iloc[0].tolist() if len(df) > 0 else []
    row1 = df.iloc[1].tolist() if len(df) > 1 else []

    if len(df.columns) == 6:
        groups.append(
            {
                "vendor_name": _clean(row1[3]) if len(row1) > 3 else "",
                "compliance_col": 3,
                "remarks_col": 4,
                "page_col": 5,
            }
        )
        return groups

    for start in VENDOR_GROUP_STARTS:
        if start >= len(df.columns):
            continue
        vendor_name = _clean(row1[start]) if len(row1) > start else ""
        if not vendor_name:
            vendor_name = _clean(row0[start]) if len(row0) > start else ""
        if not vendor_name:
            continue
        groups.append(
            {
                "vendor_name": vendor_name,
                "compliance_col": start,
                "remarks_col": start + 1,
                "page_col": start + 2,
            }
        )
    return groups


def normalize_tech_checklist(path: str) -> List[Dict[str, Any]]:
    """Load `Tech_Comp_check_list.xlsx` and return one flat record per vendor row.

    The workbook has a repeated structure:
    - row 0: item code / item name / product label
    - row 1: repeated vendor names and repeated compliance headers
    - rows 2+: actual checklist items
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)

    xls = pd.ExcelFile(p)
    rows = []
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet, header=None)
        if df.empty:
            continue

        row0 = df.iloc[0].tolist()
        item_code = _clean(df.iloc[1, 2]) if len(df.columns) > 2 and len(df) > 1 else ""
        item_name = _clean(row0[0]) if len(row0) > 0 else ""
        product_label = _clean(row0[2]) if len(row0) > 2 else ""
        vendor_groups = _find_vendor_groups(df)

        for row_idx in range(2, len(df)):
            row = df.iloc[row_idx].tolist()
            serial_no = _clean(row[0]) if len(row) > 0 else ""
            parameter_name = _clean(row[1]) if len(row) > 1 else ""
            detailed_spec = _clean(row[2]) if len(row) > 2 else ""

            if not serial_no and not parameter_name and not detailed_spec:
                continue
            if serial_no.lower() in {"s.no.", "s. no.", "s.no", "s. no"}:
                continue

            for group in vendor_groups:
                compliance = _clean(row[group["compliance_col"]]) if len(row) > group["compliance_col"] else ""
                remarks = _clean(row[group["remarks_col"]]) if len(row) > group["remarks_col"] else ""
                page_no = _clean(row[group["page_col"]]) if len(row) > group["page_col"] else ""

                if not any([compliance, remarks, page_no]):
                    continue

                rows.append(
                    {
                        "sheet": sheet,
                        "item_code": item_code,
                        "item_name": item_name,
                        "product_label": product_label,
                        "vendor_name": group["vendor_name"],
                        "serial_no": serial_no,
                        "parameter_name": parameter_name,
                        "detailed_specification": detailed_spec,
                        "compliance": compliance,
                        "remarks": remarks,
                        "page_no": page_no,
                    }
                )

    return rows


def load_master_spec(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    df = pd.read_excel(p, sheet_name=0, dtype=str).fillna("")
    expected = ["Spec_ID", "Parameter_Name", "company_Requirement"]
    cols = list(df.columns)
    if not all(c in cols for c in expected):
        mapping = {}
        for c in cols:
            lc = str(c).lower()
            if "spec" in lc:
                mapping["Spec_ID"] = c
            elif "parameter" in lc:
                mapping["Parameter_Name"] = c
            elif "require" in lc:
                mapping["company_Requirement"] = c
        missing = [name for name in expected if name not in mapping]
        if missing:
            raise ValueError(f"Missing required master spec columns: {missing}")
        df = df[[mapping[name] for name in expected]]
        df.columns = expected
    return df[expected].to_dict(orient="records")


def _print_preview():
    base = Path('data/incoming')
    tech = base / 'Tech_Comp_check_list.xlsx'
    master = base / 'master_spec.xlsx'
    print('Loading', tech)
    try:
        rows = normalize_tech_checklist(str(tech))
        print('Loaded rows:', len(rows))
        for r in rows[:10]:
            print(r)
    except Exception as e:
        print('Error loading tech checklist:', e)

    print('\nLoading', master)
    try:
        specs = load_master_spec(str(master))
        print('Loaded specs:', len(specs))
        for s in specs[:10]:
            print(s)
    except Exception as e:
        print('Error loading master spec:', e)


if __name__ == '__main__':
    _print_preview()
