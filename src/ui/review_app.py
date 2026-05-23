import streamlit as st
import sqlite3
import pandas as pd
import os
import jwt
import tempfile
import logging
from src.utils.paths import PROJECT_ROOT

try:
    import fitz
except Exception:
    fitz = None


def _verify_token(token: str) -> bool:
    review_token = os.environ.get('REVIEW_TOKEN')
    secret = os.environ.get('SECRET_KEY')
    if review_token:
        return token == review_token
    if secret:
        try:
            jwt.decode(token, secret, algorithms=['HS256'])
            return True
        except Exception:
            return False
    return False


def run() -> None:
    st.set_page_config(layout="wide", page_title="company Review Console")
    st.title("company Vendor Compliance Review")

    # Authentication gate: require REVIEW_TOKEN or a JWT signed with SECRET_KEY if those are set.
    review_token_present = bool(os.environ.get('REVIEW_TOKEN') or os.environ.get('SECRET_KEY'))
    if review_token_present:
        token = st.sidebar.text_input("Reviewer token", type="password")
        if not token:
            st.sidebar.info("Enter reviewer token to access the console")
            st.stop()
        if not _verify_token(token):
            st.sidebar.error("Invalid token")
            st.stop()
    else:
        st.sidebar.warning("No REVIEW_TOKEN or SECRET_KEY set — review console is unprotected")

    db_path = PROJECT_ROOT / "data" / "parsed" / "app.db"
    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql_query("SELECT * FROM compliance_matrix", conn)

    if df.empty:
        st.info("No audit data found. Run the pipeline first.")
        return

    st.dataframe(df)

    st.markdown("---")
    st.subheader("Override a cell")
    spec = st.text_input("Spec ID")
    vendor = st.text_input("Vendor ID")
    new_status = st.selectbox("New status", ["YES", "NEARLY OK", "NO"])
    justification = st.text_area("Justification")

    if st.button("Apply Override"):
        if not spec or not vendor or not justification:
            st.error("Spec, Vendor and justification required")
        else:
            cur = conn.cursor()
            # fetch original
            cur.execute("SELECT status, citation_doc_id, citation_excerpt FROM compliance_matrix WHERE spec_id=? AND vendor_id=?", (spec, vendor))
            row = cur.fetchone()
            original = row[0] if row else "UNKNOWN"
            citation_doc_id = row[1] if row and len(row) > 1 else None
            citation_excerpt = row[2] if row and len(row) > 2 else ""
            # update compliance_matrix
            cur.execute("UPDATE compliance_matrix SET status=?, reasoning=? WHERE spec_id=? AND vendor_id=?", (new_status, f"[OVERRIDE] {justification}", spec, vendor))
            # write to autonomous feedback loop
            cur.execute("INSERT INTO autonomous_feedback_loop (spec_id, vendor_id, original_status, corrected_status, justification, context) VALUES (?, ?, ?, ?, ?, ?)", (spec, vendor, original, new_status, justification, citation_excerpt))
            # enqueue training example if we have a citation doc
            if citation_doc_id:
                # fetch parsed_documents entry
                cur.execute("SELECT page, bbox, text FROM parsed_documents WHERE doc_id=?", (citation_doc_id,))
                pdrow = cur.fetchone()
                page = pdrow[0] if pdrow else None
                bbox = pdrow[1] if pdrow else None
                excerpt = pdrow[2] if pdrow else citation_excerpt
                cur.execute("INSERT INTO training_queue (spec_id, vendor_id, doc_id, page, bbox, excerpt, label) VALUES (?, ?, ?, ?, ?, ?, ?)", (spec, vendor, citation_doc_id, page, bbox, excerpt, new_status))
            conn.commit()
            st.success("Override applied")

    st.markdown("---")
    st.subheader("PDF Page Viewer / Citation explorer")
    # show parsed documents and let reviewer render a page
    try:
        pdfs = pd.read_sql_query("SELECT DISTINCT file_name FROM parsed_documents", conn)
    except Exception:
        pdfs = pd.DataFrame(columns=['file_name'])

    if pdfs.empty:
        st.info("No parsed documents found. You can provide a local PDF path below to preview pages.")
        pdf_choice = st.text_input("Local PDF path (absolute or relative)")
        pages = []
    else:
        pdf_choice = st.selectbox("Parsed document", list(pdfs['file_name']))
        pages_df = pd.read_sql_query("SELECT DISTINCT page FROM parsed_documents WHERE file_name=? ORDER BY page", conn, params=(pdf_choice,))
        pages = list(pages_df['page']) if not pages_df.empty else []

    page_num = None
    if pages:
        page_num = st.selectbox("Page", pages)
    else:
        page_num = st.number_input("Page number (1-based)", min_value=1, value=1)

    if st.button("Render page"):
        target = pdf_choice
        if not target:
            st.error("No PDF path provided")
        else:
            # try to resolve relative to project root
            p = Path(target)
            if not p.exists():
                p = PROJECT_ROOT / target
            if not p.exists():
                st.error(f"PDF not found: {target}")
            else:
                if fitz is None:
                    st.error("PyMuPDF (fitz) not installed — cannot render pages.")
                else:
                    try:
                        doc = fitz.open(str(p))
                        # page_num is 1-based in UI
                        pg_index = int(page_num) - 1
                        if pg_index < 0 or pg_index >= doc.page_count:
                            st.error("Page number out of range")
                        else:
                            page = doc.load_page(pg_index)
                            pix = page.get_pixmap(dpi=150)
                            img_bytes = pix.tobytes(output='png')
                            st.image(img_bytes, use_column_width=True)
                    except Exception as e:
                        logging.exception(e)
                        st.error(f"Error rendering PDF: {e}")


if __name__ == "__main__":
    run()
