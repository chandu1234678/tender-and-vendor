# company Vendor Compliance Platform — Kiro Project Brief
> Save this as `.kiro/steering/project.md` in your repo.
> Kiro reads steering files on every prompt automatically — this keeps every session on the same track.

---

## Who I Am and What I Am Building

I am **chandu1234678**, a developer building a production-grade, 100% local,
air-gapped platform that automates government procurement compliance auditing
for **company company**, one of India's largest public
sector engineering companies.

This is a real industry problem. company procurement engineers manually read
200–400 page vendor proposal PDFs and cross-check them line by line against a
master specification Excel sheet. That takes **days per tender**. I am
automating it to **under 30 minutes**, with AI agents, verbatim citations,
and a human review console — all running **completely offline on a local machine**.

---

## The Real-World Problem I Am Solving

### What the engineer does today (manually)

1. Receives one **Master Specification Excel** file — this is the checklist.
   - It has 10–50 sheets. Each sheet is one product: `NB01` (Notebook), `PC01`
     (Desktop PC), `WS01` (Workstation), `Projector`, `UP01`, `UP02` etc.
   - Each sheet has rows like:
     ```
     S.No | Parameters/Feature | Detailed Specifications       | Bidder's Compliance (Y/N)
     1    | Make & Model        | —                             | Y
     2    | Processor           | X-86, 64-bit, min 8 cores,    | Y
     |                          | 12 threads, 1.7 GHz base,     |
     |                          | 4.7 GHz turbo, 15W TDP        |
     3    | Cache               | 12MB or higher                | Y
     ```
   - The "Bidder's Compliance (Y/N)" column is what the engineer has to **fill in
     manually** for each vendor.

2. Also receives **up to 10 vendor PDF proposals** — each is 200–400 pages full
   of technical datasheets, certificates, PQR documents, test reports, delivery
   timelines, warranty terms, and penalty clauses.

3. For every spec row × every vendor PDF, the engineer reads, judges, and writes:
   - **YES** — vendor explicitly meets the requirement
   - **NEARLY OK** — vendor partially meets it or uses an equivalent
   - **NO** — vendor does not meet it or did not mention it

4. Then writes this into a comparison Excel matrix and submits it to the senior
   procurement officer for sign-off.

### What my platform does instead

- Engineer drags and drops the master Excel + vendor PDFs into the UI
- Clicks "Run Compliance Audit"
- The AI agent council evaluates every (spec × vendor) pair
- A color-coded matrix appears: **green = YES, yellow = NEARLY OK, red = NO**
- Every cell has a verbatim citation from the vendor PDF with a page number
- Engineer reviews, overrides if needed with justification
- Downloads the final Excel report
- Every override is captured for future model improvement

---

## My Full Vision — The Four Phases

I have already designed the complete system as two UML diagrams. Every phase
below maps exactly to those diagrams.

### Phase 1 — Secure Ingestion and Decomposition

The system starts in `SYSTEM_IDLE`. When the engineer drops files:

1. **company Compliance Console UI** receives the drag-and-drop upload
2. **Resilient Ingestor Engine** initializes the raw ingestion pipeline,
   passing file buffer paths
3. Uses **PyMuPDF (fitz)** to extract layout-aware text blocks from each PDF page:
   - Bounding-box coordinates per block `[x0, y0, x1, y1]`
   - Page number for every block
   - Sorted top-to-bottom, left-to-right to handle 2-column layouts
   - Complex tables are flattened into Markdown matrices
4. OCR fallback via **pytesseract** for scanned/image-only pages (200 dpi)
5. All parsed blocks are cached into **SQLite** → `parsed_documents` table
   with `INSERT INTO parsed_documents` — transactionally committed
6. The master Excel is parsed across **all sheets** simultaneously:
   - Auto-detects the header row (scans first 15 rows)
   - Forward-fills merged cells
   - Extracts: sheet name, S.No, parameter name, full requirement text
   - Every row becomes a `SpecRow` stored in `master_specs` table
7. UI shows "Documents Loaded and Ready-to-Audit"

State machine path: `SYSTEM_IDLE → RAW_INGESTION → PYMUPDF_PARSING → COORDINATE_MAPPING → MARKDOWN_TRANSFORMATION → PARSED_CACHE_COMMITTED → ORCHESTRATOR_DISPATCH`

### Phase 2 — Autonomous Multi-Agent Council Analysis

This is the core engine. For each of up to 50 spec rows × 10 vendor documents:

**Outer loop:** For each specification row (SPEC-01 to SPEC-50)
**Inner loop:** For each vendor document (Vendor_01 to Vendor_10)

1. **Orchestrator** retrieves the most relevant document segments using a
   TF-IDF mapping graph (no vector DB needed — fully local)
2. Broadcasts task to three **specialist agents in parallel**:

   - **Agent A — Technical Auditor** (`temp=0.0`, deterministic)
     Evaluates hard technical parameters: numeric values, material grades,
     processor specs, memory sizes, standards compliance.
     Returns: `{status, citation, reasoning, confidence}`

   - **Agent B — Risk Evaluator** (`temp=0.0`, deterministic)
     Evaluates legal and commercial clauses: delivery timelines, penalty
     clauses, warranty terms, regulatory frameworks, compliance declarations.
     Returns: `{status, citation, reasoning, confidence}`

   - **Agent C — Fallback Specialist** (`temp=0.1`, slightly lenient)
     Searches for "NEARLY OK" conditions: alternative configurations,
     equivalent standards, implied compliance, workarounds.
     Returns: `{status, citation, reasoning, confidence}`

3. **Consensus Judge** receives all three agent verdicts and:
   - Cross-examines claims against source citation block coordinates
   - Resolves contradictions using weighted rules
   - Extracts the most precise verbatim citation
   - Returns one verified consensus record as structured JSON

4. The consensus payload is streamed back to the orchestrator
5. **SQLite** commits structural row metrics → `compliance_matrix` table
   with `INSERT INTO compliance_matrix`
6. State persisted safely after every vendor batch

**If Ollama is not installed:** a deterministic heuristic fallback runs
instead — keyword matching + numeric value extraction — so the pipeline
always produces results.

State machine path: `PARALLEL_EXAMINATION → [TECHNICAL_AUDITOR + RISK_EVALUATOR + FALLBACK_SPECIALIST] → CONSENSUS_JUDGE → VERBATIM_CROSS_EXAMINATION → PAYLOAD_SERIALIZATION`

### Phase 3 — Human-in-the-Loop Verification and Reinforcement

1. The compiled multi-vendor aggregated data map is returned to the UI
2. The Streamlit console renders the **interactive color-coded matrix grid**:
   - Green cells = YES
   - Yellow cells = NEARLY OK
   - Red cells = NO
   - Every cell shows the verbatim citation and page number on hover/click
3. The **company Senior Procurement Officer** inspects evaluations
4. Two paths from here:
   - **Accept Row:** Engineer confirms the evaluation → `RECORD_APPROVED`
   - **Override Row:** Engineer modifies status (e.g., NO → NEARLY OK) and
     inputs an operational exception reason → `RECORD_OVERRIDDEN`
5. Every override:
   - Updates `compliance_matrix` immediately in the live transaction database
     → `LIVE_MATRIX_UPDATE`
   - Writes a delta footprint to `autonomous_feedback_loop` table for future
     model fine-tuning
   - Enqueues a training example in `training_queue`
6. UI displays "Grid Updated Successfully — Feedback Enqueued for Next Local
   Fine-Tuning Interval"

State machine path: `ANALYTICAL_STATE_PERSISTED → RENDER_COMPLIANCE_CONSOLE → [RECORD_APPROVED | RECORD_OVERRIDDEN] → LIVE_MATRIX_UPDATE → ENQUEUE_LEARNING_METRIC`

### Phase 4 — Matrix Consolidation and Output Generation

1. Audited parameter configurations are locked
2. Overridden parameter configurations are locked separately
3. **Compilation Engine** maps all audit tracks to openpyxl column generators
4. **Excel Matrix Aggregation** runs score summation rule vectors across all
   vendor profiles
5. **Automated Best Vendor Selection** logic ranks vendors by compliance score
6. Final formatted document is written straight to the local output directory
7. Engineer downloads `vendor_comparison_matrix.xlsx`

The Excel has three sheets:
- **Matrix sheet:** spec rows × vendor columns, color-coded cells
  (green/yellow/red), freeze panes, score row at bottom
- **Details sheet:** one row per (spec, vendor) with full citation, page
  number, bounding box, and reasoning from all three agents
- **Summary sheet:** vendor ranking table, score percentages, best-vendor
  recommendation call

State machine end: `COMPILATION_ENGINE → EXCEL_MATRIX_AGGREGATION → AUTOMATED_BEST_VENDOR_SELECTION → EXCEL_EXPORT_GENERATED → Secure Export Complete (0% Network Data Leaks)`

---

## What Is Already Built in My Repo

| File | Status | Notes |
|------|--------|-------|
| `src/storage/db.py` | ✅ Working | SQLite connection, WAL mode, FK enforcement |
| `src/storage/schema.sql` | ✅ Working | All 6 tables defined |
| `src/ingest/pdf_parser.py` | ✅ Working | PyMuPDF block extraction, bbox, page numbers |
| `src/ingest/ocr.py` | ✅ Working | pytesseract fallback at 200 dpi |
| `src/ingest/excel_loader.py` | ✅ Working | Multi-sheet loader with heuristic column detection |
| `src/ingest/excel_parser.py` | ⚠️ Partial | Only reads single sheet, needs multi-sheet + merged cell support |
| `src/evaluator.py` | ✅ Working | `MultiAgentEvaluator` with Ollama + heuristic fallback |
| `src/app/run_pipeline.py` | ✅ Working | Full pipeline loop: ingest → evaluate → report |
| `src/reporting/excel_report.py` | ⚠️ Partial | Exists but needs 3-sheet output + color coding |
| `src/ui/review_app.py` | ✅ Working | Streamlit review console, override form, PDF viewer |
| `src/app/api.py` | ⚠️ Partial | Has auth + health endpoint, missing /upload /run-pipeline /results |
| `src/engine/agents.py` | ❌ Stub | Three functions exist but all raise `NotImplementedError` |
| `src/engine/judge.py` | ❌ Stub | Exists but raises `NotImplementedError` |
| `src/engine/orchestrator.py` | ❌ Stub | Exists but raises `NotImplementedError` |
| `src/engine/prompts.py` | ❌ Stub | Four prompt variables are empty strings `""` |
| `scripts/generate_sample_data.py` | ✅ Working | Creates test Excel + vendor PDF |
| `scripts/bootstrap.ps1` | ✅ Working | venv setup for Windows |
| `config/settings.example.yaml` | ✅ Done | All paths and model config |

---

## What Kiro Needs to Build Next — Priority Order

### Priority 1 — Make the Engine Actually Work

The entire `src/engine/` folder is stubs. This is the heart of the system.

**1.1 — `src/engine/prompts.py`**
Write four complete prompts. Each must enforce JSON-only output with this exact schema:
```json
{"status": "YES|NO|NEARLY OK", "citation": "<verbatim text from vendor doc>", "reasoning": "...", "confidence": 0.0-1.0}
```
- `TECHNICAL_AGENT_PROMPT` — strict numeric/spec matching, temp 0.0
- `RISK_AGENT_PROMPT` — delivery/legal/penalty clauses, temp 0.0
- `FALLBACK_AGENT_PROMPT` — find equivalents and workarounds, temp 0.1
- `JUDGE_PROMPT` — synthesize all three verdicts, weighted rules

**1.2 — `src/engine/agents.py`**
Implement `run_technical_agent()`, `run_risk_agent()`, `run_fallback_agent()`:
- Each calls Ollama via `ollama.generate()` with the right prompt and temperature
- JSON response parsed from LLM output (strip markdown fences)
- Falls back to `_heuristic_eval()` logic from `src/evaluator.py` if Ollama unavailable
- Returns an `AgentResult` dataclass: `{status, citation, reasoning, confidence}`

**1.3 — `src/engine/judge.py`**
Implement `run_consensus_judge()`:
- Receives three `AgentResult` objects
- Calls Ollama with `JUDGE_PROMPT` at temp 0.0
- Deterministic fallback rules: if technical=YES and 1 other=YES → YES,
  if technical=NO and risk=NO → NO, otherwise → NEARLY OK
- Returns final `AgentResult`

**1.4 — `src/engine/orchestrator.py`**
Implement `dispatch_spec_vendor(spec_id, vendor_id)`:
- Loads spec from `master_specs` table
- Loads all blocks for this vendor from `parsed_documents` table
- TF-IDF scoring to retrieve top 5 most relevant blocks
- Merges top blocks into context string (max 4000 chars)
- Runs 3 agents in parallel via `ThreadPoolExecutor(max_workers=3)`
- Calls judge with the three results
- Returns result dict with all fields needed for `compliance_matrix`

### Priority 2 — Fix the Excel Parser for Real company Files

The current `excel_parser.py` only reads the first sheet with fixed column names.
The real company master spec Excel (like the one in the uploaded images) has:
- Multiple sheets (NB01, PC01, PC02, PC03, WS01, WS02, WS03, Projector, UP01, UP02...)
- Each sheet has a header block at the top (item name, item code)
- Then rows: S.No | Parameters/Feature | Detailed Specifications | Bidder's Compliance (Y/N)
- Merged cells in the S.No and Parameter columns (must be forward-filled)
- Variable header row location (header could be on row 3 or row 5)

The parser needs to:
- Iterate all sheets
- Scan first 15 rows to find the actual header row
- Forward-fill the first 2 columns for merged cells
- Auto-detect which column is parameter name and which is requirement text
- Generate a `spec_id` like `NB01-1`, `NB01-2`, `PC01-1` etc.
- Return a flat list of `SpecRow` dataclasses

### Priority 3 — Complete the Excel Report (3 Sheets)

The current `excel_report.py` generates something basic. It needs:
- **Sheet 1 (Matrix):** Title banner row, header row with vendor names,
  spec rows with: spec_id, sheet, parameter, requirement, then one colored
  cell per vendor. Score row at bottom. Freeze panes at E3.
- **Sheet 2 (Details):** One row per (spec, vendor) pair. Columns: spec_id,
  sheet, parameter, requirement, vendor, status, confidence, citation, page,
  reasoning. Status cells color-coded.
- **Sheet 3 (Summary):** Vendor ranking table with YES count, NEARLY OK count,
  NO count, score %, and a "RECOMMENDED / SHORTLIST / REVIEW" recommendation.

### Priority 4 — Complete the FastAPI Endpoints

The current `api.py` only has `/token`, `/health`, and `/secure`. Add:
- `POST /upload` — accept multipart files, save to `data/incoming/`
- `POST /run-pipeline` — trigger pipeline in a background thread, return `run_id`
- `GET /status/{run_id}` — return pipeline status from `pipeline_runs` table
- `GET /results` — return compliance_matrix as JSON
- `GET /report` — stream the Excel file as a download response

### Priority 5 — Wire the Pipeline to the New Engine

The current `run_pipeline.py` calls `MultiAgentEvaluator` directly from
`src/evaluator.py`. It needs to be updated to call the new orchestrator:
`src/engine/orchestrator.dispatch_spec_vendor()` instead.
The pipeline should also:
- Support a `progress_cb` callback so the Streamlit UI can show a live progress bar
- Write to `pipeline_runs` table at start, update at end or on error
- Be resumable: skip (spec, vendor) pairs that already have a result in
  `compliance_matrix`

---

## Architecture — Never Deviate From This

### Stack
- **Language:** Python 3.11+
- **PDF parsing:** PyMuPDF (fitz) — layout-aware bounding-box extraction
- **OCR fallback:** pytesseract at 200 dpi for scanned pages
- **Excel I/O:** pandas + openpyxl — multi-sheet, merged-cell aware
- **Local LLM runtime:** Ollama (llama3 or llama3:70b based on hardware)
- **Retrieval:** TF-IDF in pure Python — no vector DB, no external deps
- **Database:** SQLite — WAL mode, FK enforcement, secure_delete ON
- **API:** FastAPI + uvicorn — localhost only, JWT auth
- **UI:** Streamlit — human-in-the-loop review console
- **Report:** openpyxl — 3-sheet styled Excel matrix

### Absolute Security Rules
1. Zero network egress — no API calls to any external service ever
2. All files stay in `data/` — never write outside the project folder
3. SQLite only — no cloud DB, no Postgres unless explicitly requested
4. Audit log every override in `autonomous_feedback_loop`
5. File size cap: 200 MB per PDF to prevent resource exhaustion

### Database Tables — Never Rename These
| Table | Purpose |
|-------|---------|
| `parsed_documents` | PDF text blocks with page + bbox coordinates |
| `master_specs` | All rows from all sheets of the master Excel |
| `compliance_matrix` | Final YES/NO/NEARLY OK verdict per (spec_id, vendor_id) |
| `autonomous_feedback_loop` | Human overrides with original + corrected status |
| `training_queue` | Override examples queued for local fine-tuning |
| `audit_log` | Every pipeline action logged with timestamp |
| `pipeline_runs` | Run history: run_id, status, start/end time, error |

### Folder Layout — Never Change This
```
src/
  app/          api.py + run_pipeline.py
  engine/       agents.py, judge.py, orchestrator.py, prompts.py
  ingest/       excel_parser.py, excel_loader.py, pdf_parser.py, ocr.py
  reporting/    excel_report.py
  storage/      db.py, schema.sql
  ui/           review_app.py
  utils/        logging.py, paths.py
data/
  incoming/     drop master xlsx + vendor PDFs here
  parsed/       SQLite DB lives here (app.db)
  output/       final Excel report written here
config/
  settings.example.yaml
scripts/
  bootstrap.ps1
  generate_sample_data.py
  run_api.ps1, run_pipeline.ps1, run_review.ps1
```

---

## How to Start Each Kiro Session

Paste this at the start of every new Kiro spec or task:

```
Context: I am building the company Vendor Compliance Platform.
Read .kiro/steering/project.md for the full vision.
The repo is github.com/chandu1234678/tender-and-vendor.

Current task: [DESCRIBE THE SPECIFIC TASK HERE]

Rules:
- All code is local-first, zero network egress
- Use the exact folder structure in the steering file
- Never rename the database tables
- All agent functions must have a heuristic fallback when Ollama is unavailable
- Every verdict must store a verbatim citation from the vendor PDF text
```

---

## The One-Line Intention

> **Turn days of manual government procurement work into 30 minutes of
> automated, auditable, air-gapped AI analysis — built entirely on the
> engineer's own machine with zero data leaks.**
