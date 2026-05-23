from typing import List

import os
import pandas as pd
import sqlite3
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def _style_and_adjust_columns(wb, sheet_names: List[str]):
    green = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    yellow = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
    red = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

    if "Matrix" in sheet_names:
        ws = wb["Matrix"]
        ws.freeze_panes = "B2"
        for row in ws.iter_rows(min_row=2, min_col=2):
            for cell in row:
                val = (cell.value or "").upper()
                cell.alignment = Alignment(wrap_text=True)
                if val.startswith("YES"):
                    cell.fill = green
                elif val.startswith("NEARLY"):
                    cell.fill = yellow
                elif val.startswith("NO"):
                    cell.fill = red

    for sheet_name in sheet_names:
        if sheet_name not in wb.sheetnames:
            continue
        sheet = wb[sheet_name]
        for col_idx, column_cells in enumerate(sheet.columns, start=1):
            max_length = 0
            for cell in column_cells:
                try:
                    max_length = max(max_length, len(str(cell.value)) if cell.value is not None else 0)
                except Exception:
                    pass
            sheet.column_dimensions[get_column_letter(col_idx)].width = min(max(max_length + 2, 12), 45)
        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")


def build_excel_report(output_path: str, db_path: str = "data/parsed/app.db") -> None:
    """Build a styled Excel report with Matrix, Details, and Summary sheets.

    Additionally generate per-vendor Excel files containing columns:
    `spec_id`, `parameter_name`, `company_requirement`, `OK` (Yes/No), `Remarks`, `Page No`.
    """
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM compliance_matrix", conn)
    specs = pd.read_sql_query("SELECT spec_id, parameter_name, company_requirement FROM master_specs", conn)
    conn.close()

    if df.empty:
        df = pd.DataFrame(
            columns=[
                "spec_id",
                "vendor_id",
                "status",
                "citation",
                "reasoning",
                "confidence",
                "citation_doc_id",
                "citation_excerpt",
                "citation_page",
            ]
        )

    pivot = df.pivot(index="spec_id", columns="vendor_id", values="status") if not df.empty else pd.DataFrame()
    details = df.sort_values(["spec_id", "vendor_id"]) if not df.empty else df
    summary = (
        df.groupby("vendor_id", dropna=False)
        .agg(
            total_specs=("spec_id", "count"),
            yes_count=("status", lambda s: (s.str.upper().str.startswith("YES")).sum()),
            nearly_ok_count=("status", lambda s: (s.str.upper().str.startswith("NEARLY")).sum()),
            no_count=("status", lambda s: (s.str.upper().str.startswith("NO")).sum()),
            avg_confidence=("confidence", "mean"),
        )
        .reset_index()
        if not df.empty
        else pd.DataFrame(columns=["vendor_id", "total_specs", "yes_count", "nearly_ok_count", "no_count", "avg_confidence"])
    )
    summary["score"] = summary["yes_count"] * 2 + summary["nearly_ok_count"]
    summary = summary.sort_values(["score", "avg_confidence"], ascending=[False, False])

    # Ensure output directory exists
    out_dir = os.path.dirname(output_path) or "."
    os.makedirs(out_dir, exist_ok=True)

    # Write combined workbook
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        pivot.to_excel(writer, sheet_name="Matrix")
        details.to_excel(writer, sheet_name="Details", index=False)
        summary.to_excel(writer, sheet_name="Summary", index=False)

    wb = load_workbook(output_path)
    _style_and_adjust_columns(wb, ["Matrix", "Details", "Summary"])
    wb.save(output_path)

    # Generate per-vendor files
    # Merge details with specs to include parameter info where available
    if not df.empty:
        merged = details.merge(specs, on="spec_id", how="left")
    else:
        merged = details

    # Use the incoming Tech_Comp template to create per-vendor files that match layout exactly
    template_path = os.path.join('data', 'incoming', 'Tech_Comp_check_list.xlsx')
    if os.path.exists(template_path) and not merged.empty:
        # Build a lookup from (spec_id, vendor_id) -> row values
        lookup = {}
        for _, row in merged.iterrows():
            lookup_key = (row.get('spec_id'), row.get('vendor_id'))
            lookup[lookup_key] = {
                'status': row.get('status'),
                'reasoning': row.get('reasoning'),
                'citation_excerpt': row.get('citation_excerpt'),
                'citation_page': row.get('citation_page'),
            }

        for vendor_id in merged['vendor_id'].dropna().unique():
            # save a copy of the template as the vendor workbook
            vendor_file = os.path.join(out_dir, f"vendor_{vendor_id}.xlsx")
            tpl_wb = load_workbook(template_path)
            tpl_wb.save(vendor_file)
            vwb = load_workbook(vendor_file)

            for sheet_name in vwb.sheetnames:
                ws = vwb[sheet_name]
                # Find header row by searching for a cell that contains 'S. No.' or 'S. No'
                header_row = None
                for r in range(1, min(10, ws.max_row) + 1):
                    for c in range(1, ws.max_column + 1):
                        val = ws.cell(row=r, column=c).value
                        if val and isinstance(val, str) and 's. no' in val.lower():
                            header_row = r
                            break
                    if header_row:
                        break
                if not header_row:
                    # fallback to row 3
                    header_row = 3

                # locate the template columns for compliance, remarks, page no by header text
                comp_col = None
                remarks_col = None
                page_col = None
                for c in range(1, ws.max_column + 1):
                    h = ws.cell(row=header_row, column=c).value
                    if not h or not isinstance(h, str):
                        continue
                    lh = h.lower()
                    if 'compliance' in lh or 'bidder' in lh and 'y/n' in lh:
                        comp_col = c
                    if 'remark' in lh:
                        remarks_col = c
                    if 'page' in lh:
                        page_col = c

                # If any column not found, append them to the right
                append_start = ws.max_column + 1
                if comp_col is None:
                    comp_col = append_start
                    ws.cell(row=header_row, column=comp_col, value="Bidder's Compliance (Y/N)")
                    append_start += 1
                if remarks_col is None:
                    remarks_col = append_start
                    ws.cell(row=header_row, column=remarks_col, value='Remarks')
                    append_start += 1
                if page_col is None:
                    page_col = append_start
                    ws.cell(row=header_row, column=page_col, value='Page No. in Bid document')
                    append_start += 1

                # For each spec belonging to this sheet, write the vendor's values
                sheet_prefix = sheet_name
                # master spec ids use prefix like 'NB01-1'
                cur_specs = specs[specs['spec_id'].str.startswith(f"{sheet_prefix}-", na=False)]
                for _, srow in cur_specs.iterrows():
                    try:
                        idx = int(srow.get('spec_id').split('-')[-1])
                    except Exception:
                        idx = srow.get('row_index') or None
                    if not idx:
                        continue
                    target_row = header_row + idx
                    key = (srow.get('spec_id'), vendor_id)
                    val = lookup.get(key, {})
                    status = val.get('status')
                    reasoning = val.get('reasoning') or val.get('citation_excerpt') or ''
                    page_no = val.get('citation_page')

                    # map status to Y/N
                    ok_val = ''
                    if status and str(status).strip().upper().startswith('YES'):
                        ok_val = 'Y'
                    elif status and str(status).strip().upper().startswith('NO'):
                        ok_val = 'N'

                    # Write values safely into cells that may be part of merged ranges
                    from openpyxl.cell.cell import MergedCell

                    def safe_write(ws, row, col, value):
                        cell = ws.cell(row=row, column=col)
                        if isinstance(cell, MergedCell):
                            # find the merged range that contains this cell
                            for mr in ws.merged_cells.ranges:
                                if mr.min_row <= row <= mr.max_row and mr.min_col <= col <= mr.max_col:
                                    ws.cell(row=mr.min_row, column=mr.min_col, value=value)
                                    return
                            # fallback
                            return
                        else:
                            ws.cell(row=row, column=col, value=value)

                    safe_write(ws, target_row, comp_col, ok_val)
                    safe_write(ws, target_row, remarks_col, reasoning)
                    safe_write(ws, target_row, page_col, page_no)

            _style_and_adjust_columns(vwb, vwb.sheetnames)
            vwb.save(vendor_file)
    else:
        # fallback: previous simple export if template missing or no data
        for vendor_id in merged["vendor_id"].dropna().unique():
            vdf = merged[merged["vendor_id"] == vendor_id].copy()
            def map_ok(s):
                if not s or pd.isna(s):
                    return ""
                us = str(s).upper()
                if us.startswith("YES"):
                    return "Yes"
                if us.startswith("NO"):
                    return "No"
                return ""
            vdf["OK"] = vdf["status"].apply(map_ok)
            vdf["Remarks"] = vdf["reasoning"].fillna("").astype(str).where(lambda x: x.str.strip() != "", vdf["citation_excerpt"].fillna(""))
            vdf["Page No"] = vdf["citation_page"]
            vendor_cols = ["spec_id", "parameter_name", "company_requirement", "OK", "Remarks", "Page No"]
            for c in vendor_cols:
                if c not in vdf.columns:
                    vdf[c] = ""
            vendor_file = os.path.join(out_dir, f"vendor_{vendor_id}.xlsx")
            vdf.loc[:, vendor_cols].to_excel(vendor_file, index=False, sheet_name="Vendor Report")
            vwb = load_workbook(vendor_file)
            _style_and_adjust_columns(vwb, ["Vendor Report"])
            vwb.save(vendor_file)
