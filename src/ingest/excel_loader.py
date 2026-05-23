from pathlib import Path
import pandas as pd
import os
from typing import List, Dict, Any


def normalize_tech_checklist(path: str) -> List[Dict[str, Any]]:
    """Load `Tech_Comp_check_list.xlsx` and return structured rows.

    This function attempts to extract for each sheet a list of item rows
    with normalized keys: `sheet`, `item_code`, `description`, `vendor_response`.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)

    xls = pd.ExcelFile(p)
    rows = []
    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet, header=0)
        # Heuristic: first column often contains item label or code
        colnames = list(df.columns)
        # Try to find a vendor response column
        vendor_col = None
        for c in colnames:
            if isinstance(c, str) and 'vendor' in c.lower():
                vendor_col = c
                break
        # fallback: look for columns named 'Vendor Response' exactly
        if vendor_col is None and 'Vendor Response' in colnames:
            vendor_col = 'Vendor Response'

        for _, r in df.iterrows():
            item_code = None
            description = None
            vendor_response = None

            # heuristics for common layout
            if len(colnames) >= 1:
                item_code = r[colnames[0]] if pd.notna(r[colnames[0]]) else None
            if len(colnames) >= 3:
                description = r[colnames[2]] if pd.notna(r[colnames[2]]) else None
            # vendor response
            if vendor_col is not None:
                vendor_response = r.get(vendor_col)
            else:
                # try to locate a likely vendor name/value in later columns
                for c in colnames[3:6]:
                    try:
                        if pd.notna(r[c]):
                            vendor_response = r[c]
                            break
                    except Exception:
                        continue

            rows.append({
                'sheet': sheet,
                'item_code': item_code if item_code is not None else '',
                'description': description if description is not None else '',
                'vendor_response': vendor_response if vendor_response is not None else '',
            })

    return rows


def load_master_spec(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    df = pd.read_excel(p, sheet_name=0)
    expected = ['Spec_ID', 'Parameter_Name', 'BHEL_Requirement']
    # normalize columns if necessary
    cols = list(df.columns)
    if all(c in cols for c in expected):
        out = df[expected].fillna('').to_dict(orient='records')
    else:
        # try to map by fuzzy names
        mapping = {}
        for c in cols:
            lc = str(c).lower()
            if 'spec' in lc:
                mapping['Spec_ID'] = c
            elif 'parameter' in lc:
                mapping['Parameter_Name'] = c
            elif 'require' in lc:
                mapping['BHEL_Requirement'] = c
        out = df[list(mapping.values())].fillna('').to_dict(orient='records')
        # rename keys
        out = [
            {
                'Spec_ID': r[list(mapping.values())[0]],
                'Parameter_Name': r[list(mapping.values())[1]] if len(mapping.values())>1 else '',
                'BHEL_Requirement': r[list(mapping.values())[2]] if len(mapping.values())>2 else '',
            }
            for r in out
        ]
    return out


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
