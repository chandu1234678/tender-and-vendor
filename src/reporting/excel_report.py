from typing import List

import os
import pandas as pd
import sqlite3
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def _style_and_adjust_columns(wb, sheet_names: List[str]):
    green = PatternFill(fill_type="solid", fgColor="C6EFCE")
    yellow = PatternFill(fill_type="solid", fgColor="FFEB9C")
    red = PatternFill(fill_type="solid", fgColor="FFC7CE")
    header_fill = PatternFill(fill_type="solid", fgColor="D9E1F2")
    title_fill = PatternFill(fill_type="solid", fgColor="BDD7EE")

    if "Matrix" in sheet_names:
        ws = wb["Matrix"]
        ws.freeze_panes = "E3"
        header_vals = [str(cell.value or "").lower() for cell in ws[2]]
        vendor_start_col = 2
        if "company_requirement" in header_vals:
            vendor_start_col = header_vals.index("company_requirement") + 2
        for row in ws.iter_rows(min_row=3, max_row=ws.max_row, min_col=vendor_start_col, max_col=ws.max_column):
            for cell in row:
                val = str(cell.value or "").upper()
                cell.alignment = Alignment(wrap_text=True)
                if val.startswith("YES"):
                    cell.fill = green
                elif val.startswith("NEARLY"):
                    cell.fill = yellow
                elif val.startswith("NO"):
                    cell.fill = red
        # style title and header rows
        for cell in ws[1]:
            cell.fill = title_fill
            cell.font = Font(bold=True)
        for cell in ws[2]:
            cell.fill = header_fill
            cell.font = Font(bold=True)

    for sheet_name in sheet_names:
        if sheet_name not in wb.sheetnames:
            continue
        sheet = wb[sheet_name]
        for row in sheet.iter_rows(min_row=1, max_row=1):
            for cell in row:
                if cell.value:
                    cell.font = Font(bold=True)
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

    if "Matrix" in sheet_names:
        ws = wb["Matrix"]
        header_vals = [str(cell.value or "").lower() for cell in ws[2]]
        vendor_start_col = 2
        if "company_requirement" in header_vals:
            vendor_start_col = header_vals.index("company_requirement") + 2
        for row in ws.iter_rows(min_row=3, max_row=ws.max_row, min_col=vendor_start_col, max_col=ws.max_column):
            for cell in row:
                val = str(cell.value or "").upper()
                if val.startswith("YES"):
                    cell.fill = green
                elif val.startswith("NEARLY"):
                    cell.fill = yellow
                elif val.startswith("NO"):
                    cell.fill = red


def build_excel_report(output_path: str, db_path: str = "data/parsed/app.db") -> None:
    """Build a styled Excel report with Matrix, Details, and Summary sheets."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM compliance_matrix", conn)
    specs = pd.read_sql_query(
        "SELECT spec_id, sheet_name, parameter_name, company_requirement, row_index FROM master_specs",
        conn,
    )
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
    if not specs.empty:
        matrix = specs.merge(pivot, left_on="spec_id", right_index=True, how="left")
    else:
        matrix = pivot.reset_index()

    if not pivot.empty:
        score = (
            pivot.fillna("")
            .apply(lambda col: col.map(lambda v: 2 if str(v).upper().startswith("YES") else 1 if str(v).upper().startswith("NEARLY") else 0))
            .sum()
        )
        score_row = {"spec_id": "SCORE"}
        if "sheet_name" in matrix.columns:
            score_row["sheet_name"] = ""
        if "parameter_name" in matrix.columns:
            score_row["parameter_name"] = "Score"
        if "company_requirement" in matrix.columns:
            score_row["company_requirement"] = ""
        score_row.update(score.to_dict())
        matrix = pd.concat([matrix, pd.DataFrame([score_row])], ignore_index=True)
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
    summary["score_percent"] = summary.apply(
        lambda row: round((row["score"] / (max(1, row["total_specs"]) * 2)) * 100, 2), axis=1
    )
    summary["recommendation"] = summary["score_percent"].apply(
        lambda v: "RECOMMENDED" if v >= 85 else "SHORTLIST" if v >= 70 else "REVIEW"
    )
    summary = summary.sort_values(["score_percent", "avg_confidence"], ascending=[False, False])

    # Ensure output directory exists
    out_dir = os.path.dirname(output_path) or "."
    os.makedirs(out_dir, exist_ok=True)

    # Write combined workbook
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        matrix.to_excel(writer, sheet_name="Matrix", index=False)
        if not details.empty and not specs.empty:
            details = details.merge(specs, on="spec_id", how="left")
            details = details[
                [
                    "spec_id",
                    "sheet_name",
                    "parameter_name",
                    "company_requirement",
                    "vendor_id",
                    "status",
                    "confidence",
                    "citation",
                    "citation_page",
                    "citation_bbox",
                    "reasoning",
                ]
            ]
        details.to_excel(writer, sheet_name="Details", index=False)
        summary.to_excel(writer, sheet_name="Summary", index=False)

    wb = load_workbook(output_path)
    if "Matrix" in wb.sheetnames:
        ws = wb["Matrix"]
        ws.insert_rows(1)
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ws.max_column)
        ws.cell(row=1, column=1, value="company Vendor Compliance Matrix")
    _style_and_adjust_columns(wb, ["Matrix", "Details", "Summary"])
    if "Matrix" in wb.sheetnames:
        ws = wb["Matrix"]
        header_vals = [str(cell.value or "").lower() for cell in ws[2]]
        vendor_start_col = 2
        if "company_requirement" in header_vals:
            vendor_start_col = header_vals.index("company_requirement") + 2
        green = PatternFill(fill_type="solid", fgColor="C6EFCE")
        yellow = PatternFill(fill_type="solid", fgColor="FFEB9C")
        red = PatternFill(fill_type="solid", fgColor="FFC7CE")
        for row in ws.iter_rows(min_row=3, max_row=ws.max_row, min_col=vendor_start_col, max_col=ws.max_column):
            for cell in row:
                val = str(cell.value or "").upper()
                if val.startswith("YES"):
                    cell.fill = green
                elif val.startswith("NEARLY"):
                    cell.fill = yellow
                elif val.startswith("NO"):
                    cell.fill = red
    wb.save(output_path)

    # Generate per-vendor files
    # Merge details with specs to include parameter info where available
    if not df.empty:
        merged = details.merge(specs, on="spec_id", how="left")
    else:
        merged = details

    # Use the incoming Tech_Comp template to create per-vendor files that match layout exactly
    template_path = os.path.join("data", "incoming", "Tech_Comp_check_list.xlsx")
    if os.path.exists(template_path) and not merged.empty:
        # Build a lookup from (spec_id, vendor_id) -> row values
        lookup = {}
        for _, row in merged.iterrows():
            lookup_key = (row.get('spec_id'), row.get('vendor_id'))
            lookup[lookup_key] = {
                'status': row.get('status'),
                'reasoning': row.get('reasoning') or '',
                'citation_excerpt': row.get('citation_excerpt') or row.get('citation') or '',
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
                cur_specs = specs[specs['sheet_name'].fillna('') == sheet_name]
                for _, srow in cur_specs.iterrows():
                    idx = srow.get('row_index')
                    if not idx:
                        continue
                    target_row = header_row + int(idx)
                    key = (srow.get('spec_id'), vendor_id)
                    val = lookup.get(key, {})
                    status = val.get('status')
                    page_no = val.get('citation_page')
                    excerpt = val.get('citation_excerpt') or ''
                    reasoning = val.get('reasoning') or ''
                    if excerpt:
                        reasoning = excerpt if not reasoning else f"{reasoning} | {excerpt}"
                    if page_no:
                        reasoning = f"Page {page_no}: {reasoning}" if reasoning else f"Page {page_no}"

                    # map status to Y/N
                    ok_val = ''
                    if status and str(status).strip().upper().startswith('YES'):
                        ok_val = 'Y'
                    elif status and str(status).strip().upper().startswith('NO'):
                        ok_val = 'N'
                    elif status and str(status).strip().upper().startswith('NEARLY'):
                        ok_val = 'N'
                        if reasoning:
                            reasoning = f"NEARLY OK: {reasoning}"

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
