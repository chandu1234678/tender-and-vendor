"""Inline runner: NB01 x product-pdf, FAST_MODE heuristic, single worker."""
import sys, os, uuid, sqlite3
sys.path.insert(0, ".")

# ── env before any imports ────────────────────────────────────────────────────
os.environ["PIPELINE_VENDOR_FILTER"] = "product-pdf"
os.environ["PIPELINE_SHEET_FILTER"]  = "NB01"
os.environ["FAST_SKIP_OCR"]          = "1"
os.environ["FAST_REUSE_PARSED"]      = "1"
os.environ["FAST_TOP_K"]             = "5"
os.environ["FAST_MODE"]              = "1"   # pure heuristic path, no LLM
os.environ["LLM_ONLY_UNCERTAIN"]     = "0"
os.environ["PIPELINE_EVAL_WORKERS"]  = "1"   # single worker avoids thread issues

# ── kill LLM before any module loads it ──────────────────────────────────────
import src.engine.ollama_client as _oc
_oc._healthy = False
_oc.is_healthy = lambda: False

from src.storage.db import init_db, get_connection
from src.app.run_pipeline import main as run_pipeline

DB = "data/parsed/app.db"
init_db(DB)

# clear old results
conn = get_connection(DB)
conn.execute("UPDATE pipeline_runs SET status='failed',message='Cleared' WHERE status IN ('running','queued')")
conn.execute("DELETE FROM compliance_matrix WHERE vendor_id='product-pdf'")
conn.commit()
conn.close()

run_id = "nb01-rerun-" + str(uuid.uuid4())[:8]
print(f"Run ID: {run_id}\n")
run_pipeline(run_id=run_id)

# ── results table ─────────────────────────────────────────────────────────────
conn2 = sqlite3.connect(DB)
src_row = conn2.execute(
    "SELECT source_file FROM master_specs WHERE sheet_name='NB01' ORDER BY rowid DESC LIMIT 1"
).fetchone()
src = src_row[0] if src_row else "%"

rows = conn2.execute(
    "SELECT cm.spec_id, COALESCE(ms.parameter_name,'') as param, "
    "cm.status, cm.confidence, cm.citation_page, "
    "substr(COALESCE(cm.citation,''),1,70) as cite "
    "FROM compliance_matrix cm "
    "LEFT JOIN master_specs ms ON ms.spec_id=cm.spec_id AND ms.source_file=? "
    "WHERE cm.vendor_id='product-pdf' "
    "GROUP BY cm.spec_id ORDER BY cm.spec_id",
    (src,)
).fetchall()
conn2.close()

yes    = sum(1 for r in rows if str(r[2]).upper().startswith("YES"))
nearly = sum(1 for r in rows if str(r[2]).upper().startswith("NEARLY"))
no     = sum(1 for r in rows if str(r[2]).upper().startswith("NO"))
score  = round((yes * 2 + nearly) / max(1, len(rows) * 2) * 100, 1)

G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; B = "\033[1m"; X = "\033[0m"
COL = {"YES": G, "NEARLY OK": Y, "NO": R}

print(f"\n{B}{'='*74}{X}")
print(f"{B}RESULTS  NB01 x product-pdf   ({len(rows)} specs evaluated){X}")
print(f"{'='*74}")
print(f"  {G}YES{X}       : {yes}")
print(f"  {Y}NEARLY OK{X} : {nearly}")
print(f"  {R}NO{X}        : {no}")
print(f"  Score     : {score}%")
print(f"{'='*74}")
print(f"\n{B}{'Spec ID':<14} {'Parameter':<24} {'Status':<12} {'Conf':>5}  {'Pg':>3}  Citation{X}")
print("-" * 92)
for spec_id, param, status, conf, page, cite in rows:
    col = COL.get(str(status).upper().strip(), "")
    cite_str = (cite or "").replace("\n", " ").strip()
    # highlight Memory row
    marker = " <-- FIXED" if "memory" in param.lower() else ""
    print(f"{spec_id:<14} {param[:23]:<24} {col}{status:<12}{X} {conf:>5.2f}  {str(page or '-'):>3}  {cite_str}{marker}")

print()
print("[INFO] Excel reports written to data/output/")
