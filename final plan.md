1. Steering File — paste this first
Save as .kiro/steering/project.md — Kiro reads this on every single prompt automatically.

# Project: Tender & Vendor Compliance Platform

## What This Is
A 100% local, air-gapped, Python-based platform that automates
government procurement compliance auditing for company (Bharat Heavy
Electricals Limited). It replaces manual Excel work done by
procurement engineers who currently read 200–400 page vendor PDFs
by hand and fill in a Yes/No compliance checklist.

## The Core Problem We Are Solving
- A company engineer receives 1 master spec Excel (with 10–50 sheets,
  each sheet = one product like NB01, PC01, WS01, Projector, etc.)
- Each sheet has rows: S.No | Parameter/Feature | Detailed Specification | Bidder's Compliance (Y/N)
- The engineer also receives up to 10 vendor PDF proposals
  (200–400 pages each, with technical specs, certificates, PQR docs)
- The engineer must manually cross-check every spec row against
  every vendor PDF and mark YES / NO / NEARLY OK
- This takes days. We automate it to minutes.

## The Output
A color-coded Excel matrix: rows = spec parameters, columns = vendors,
cells = YES (green) / NEARLY OK (yellow) / NO (red), with verbatim
citations from the vendor PDF and page numbers. Plus a Summary sheet
with vendor ranking and best-vendor recommendation.

## Architecture — Never Deviate From This
- Language: Python 3.11+
- PDF parsing: PyMuPDF (fitz) — layout-aware bounding-box extraction
- Excel parsing: pandas + openpyxl — multi-sheet, merged-cell aware
- OCR fallback: pytesseract — for scanned vendor PDFs
- AI evaluation: Ollama (local LLM, llama3 or similar) — 3 agents + 1 judge
  - Agent 1: Technical Auditor (temp=0.0, strict numeric/spec matching)
  - Agent 2: Risk Evaluator (temp=0.0, legal/delivery/penalty clauses)
  - Agent 3: Fallback Specialist (temp=0.1, finds "nearly OK" equivalents)
  - Judge: Consensus Judge synthesizes all 3 into final YES/NO/NEARLY OK
- If Ollama not available: deterministic heuristic fallback (keyword + numeric matching)
- State: SQLite (WAL mode, FK enforcement, secure_delete ON)
- UI: Streamlit — human-in-the-loop review console
- API: FastAPI — for pipeline triggering and status
- Report: openpyxl — styled Excel matrix (3 sheets: Matrix, Details, Summary)
- Zero network egress. Everything runs on the engineer's local machine.

## Database Tables — Never Change These Names
- parsed_documents — PDF blocks with page + bounding box coordinates
- master_specs — all rows from the master Excel, all sheets
- compliance_matrix — final YES/NO/NEARLY OK verdict per (spec_id, vendor_id)
- autonomous_feedback_loop — human overrides captured for fine-tuning
- training_queue — override examples queued for future model improvement
- audit_log — every action logged
- pipeline_runs — run history with status and error messages

## File/Folder Layout — Respect This Always

src/
app/          FastAPI app (api.py) + pipeline runner (run_pipeline.py)
engine/       agents.py, judge.py, orchestrator.py, prompts.py
ingest/       excel_parser.py, pdf_parser.py, ocr.py
reporting/    excel_report.py
storage/      db.py, schema.sql
ui/           review_app.py (Streamlit)
utils/        logging.py, paths.py
data/
incoming/     drop master xlsx + vendor PDFs here
parsed/       SQLite DB lives here
output/       final Excel report written here
config/
settings.yaml

## Non-Negotiables
1. No data ever leaves the machine. No API calls to external services.
2. Every verdict must have a verbatim citation from the vendor PDF.
3. All DB writes are transactional — if a run fails, partial results are kept.
4. The Streamlit UI must support human override with justification capture.
5. The Excel output must be color-coded and downloadable by the engineer.
6. Support up to 50 spec rows × 10 vendor PDFs in a single run.
7. Heuristic fallback must always work even without Ollama installed.

2. The Master Spec Prompt — paste into Kiro's spec panel
This is your one big opening prompt that Kiro will expand into requirements + design + tasks:
Build a complete, production-grade, local-first company Vendor Compliance 
Automation Platform.

Context: company procurement engineers manually cross-check a master Excel 
specification checklist (10–50 sheets, each sheet is a product like NB01, 
PC01, WS01, Projector) against up to 10 vendor PDF proposals (200–400 pages 
each). Each spec row has a parameter name and a detailed requirement. The 
engineer marks it YES, NO, or NEARLY OK for each vendor. This takes days. 
We automate it to under 30 minutes.

The system must:
1. Accept a master spec Excel upload and multiple vendor PDF uploads via a 
   Streamlit drag-and-drop UI
2. Parse the Excel across all sheets — handle merged cells, variable headers, 
   forward-fill — extracting: sheet name, S.No, parameter, full requirement text
3. Parse each vendor PDF with PyMuPDF — layout-aware block extraction with 
   page numbers and bounding boxes. OCR fallback via pytesseract for scanned pages.
4. Store all parsed content in SQLite (WAL mode, air-gapped, no network)
5. For each (spec_row × vendor) pair, run a 3-agent AI council via local Ollama:
   - Technical Auditor: strict numeric/standard matching at temp=0.0
   - Risk Evaluator: legal/delivery/warranty clauses at temp=0.0  
   - Fallback Specialist: finds equivalent/alternative compliance at temp=0.1
   - Consensus Judge: synthesizes all 3 into final YES / NO / NEARLY OK
   - If Ollama unavailable, use deterministic keyword+numeric heuristic fallback
6. Persist every verdict with: status, confidence score, verbatim citation, 
   page number, bounding box coordinates, agent reasoning
7. Build a Streamlit review console where the engineer can:
   - See the color-coded matrix (green=YES, yellow=NEARLY OK, red=NO)
   - Click any cell to see the full citation and agent reasoning
   - Override any verdict with justification (captured in feedback loop table)
   - Render any PDF page inline to verify citations
   - Download the final Excel report
8. Generate a styled Excel report with 3 sheets:
   - Matrix: spec rows × vendor columns, color-coded cells
   - Details: full row-per-pair with citations, page refs, reasoning
   - Summary: vendor ranking by compliance score, best-vendor call
9. FastAPI backend with /upload, /run-pipeline, /status/{run_id}, /results endpoints
10. Everything runs with: pip install -r requirements.txt + streamlit run src/ui/review_app.py
    Zero configuration needed beyond dropping files into data/incoming/

3. Task List — paste as your to-do in Kiro
Save as .kiro/specs/tender-vendor/tasks.md. These are the exact tasks for Kiro to execute one by one:
markdown# Tender & Vendor Platform — Task List

## Phase 1: Secure Ingestion & Decomposition
- [ ] 1.1 Implement `src/storage/db.py` — SQLite connection with WAL, FK, secure_delete, all 6 tables from schema.sql
- [ ] 1.2 Implement `src/ingest/excel_parser.py` — multi-sheet parser, auto-detect header row, merged-cell forward-fill, return list of SpecRow dataclasses
- [ ] 1.3 Implement `src/ingest/pdf_parser.py` — PyMuPDF block extraction, bounding boxes, page numbers, sort blocks top-to-bottom left-to-right, return PdfBlock list
- [ ] 1.4 Implement `src/ingest/ocr.py` — pytesseract fallback for scanned pages, 200 dpi rasterization
- [ ] 1.5 Write `scripts/generate_sample_data.py` — creates sample master Excel (3 sheets, 5 specs each) + 2 sample vendor PDFs for testing

## Phase 2: Multi-Agent Council Evaluation
- [ ] 2.1 Write all 4 prompts in `src/engine/prompts.py` — TECHNICAL_AGENT_PROMPT, RISK_AGENT_PROMPT, FALLBACK_AGENT_PROMPT, JUDGE_PROMPT. Each must enforce JSON-only output with schema: {status, citation, reasoning, confidence}
- [ ] 2.2 Implement `src/engine/agents.py` — run_technical_agent(), run_risk_agent(), run_fallback_agent() each calling Ollama at correct temperature, with heuristic fallback
- [ ] 2.3 Implement `src/engine/judge.py` — run_consensus_judge() combining 3 agent results, deterministic fallback rules
- [ ] 2.4 Implement `src/engine/orchestrator.py` — TF-IDF retrieval to find top-5 relevant blocks per spec, parallel dispatch of 3 agents via ThreadPoolExecutor, call judge, return structured result dict
- [ ] 2.5 Implement `src/app/run_pipeline.py` — full pipeline: ingest specs → ingest vendor PDFs → evaluate all pairs → build report. Progress callback support. Transactional DB writes per vendor.

## Phase 3: Human-in-the-Loop Review UI
- [ ] 3.1 Implement `src/ui/review_app.py` — Streamlit app with:
  - Drag-and-drop file upload for master Excel + vendor PDFs
  - Pipeline trigger button with live progress bar
  - Color-coded matrix grid (green/yellow/red cells)
  - Click-to-inspect: show citation, page number, agent reasoning per cell
  - Override form: new status dropdown + justification text → writes to autonomous_feedback_loop + compliance_matrix
  - PDF page renderer: show vendor PDF page inline with PyMuPDF
  - Download button for final Excel report
- [ ] 3.2 Add sidebar filters: filter by sheet/product, filter by status, filter by vendor
- [ ] 3.3 Add summary stats: total specs, YES/NEARLY OK/NO counts per vendor, best vendor callout

## Phase 4: Excel Report Generation
- [ ] 4.1 Implement `src/reporting/excel_report.py` — Sheet 1 (Matrix): color-coded, freeze panes, score row. Sheet 2 (Details): full citations + page refs. Sheet 3 (Summary): ranked vendor table
- [ ] 4.2 Ensure report saves to `data/output/vendor_comparison_matrix.xlsx` and is downloadable from Streamlit UI

## Phase 5: FastAPI Backend
- [ ] 5.1 Implement `src/app/api.py` — endpoints: POST /upload (accept files → save to data/incoming/), POST /run-pipeline (trigger pipeline in background thread), GET /status/{run_id} (pipeline progress), GET /results (compliance_matrix as JSON), GET /report (download Excel file)
- [ ] 5.2 Add JWT auth to API (SECRET_KEY from env var)

## Phase 6: Config & Hardening
- [ ] 6.1 Write `config/settings.yaml` — paths, model name, OCR toggle, air-gap flag
- [ ] 6.2 Write `requirements.txt` — all deps pinned
- [ ] 6.3 Write `scripts/bootstrap.ps1` and `scripts/bootstrap.sh` — create venv, install deps, create data dirs, run sample data generator
- [ ] 6.4 Write `README.md` — quick start in 3 commands, architecture diagram (Mermaid), screenshot of the review console

## Phase 7: Testing
- [ ] 7.1 Write `tests/test_excel_parser.py` — test multi-sheet parsing, merged cells, missing columns
- [ ] 7.2 Write `tests/test_pdf_parser.py` — test block extraction, sort order, OCR fallback
- [ ] 7.3 Write `tests/test_heuristic_agent.py` — test YES/NO/NEARLY OK classification with known inputs
- [ ] 7.4 Write `tests/test_pipeline.py` — end-to-end integration test with sample data
- [ ] 7.5 Write `tests/test_excel_report.py` — verify 3 sheets, correct colors, correct data

4. Agent Hook — auto-run linting after every agent session
Save as .kiro/hooks/lint-after-agent.json:
json{
  "name": "Lint & Format After Agent",
  "version": "1.0.0",
  "when": {
    "type": "agentStop"
  },
  "then": {
    "type": "runCommand",
    "command": "cd ${workspaceFolder} && python -m ruff check src/ --fix && python -m ruff format src/"
  }
}
And a hook to auto-run tests when you edit the engine:
json{
  "name": "Run Tests on Engine Edit",
  "version": "1.0.0",
  "when": {
    "type": "fileEdited",
    "patterns": ["src/engine/**/*.py", "src/ingest/**/*.py"]
  },
  "then": {
    "type": "askAgent",
    "prompt": "A core engine or ingest file was edited. Check if the corresponding test file in tests/ needs to be updated to match the new logic. If tests exist, run them mentally and flag any that would now fail."
  }
}