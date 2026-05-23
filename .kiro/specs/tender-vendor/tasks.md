# Tender & Vendor Platform - Task List

## Phase 1: Secure Ingestion & Decomposition
- [ ] 1.1 Implement `src/storage/db.py` - SQLite connection with WAL, FK, secure_delete, and all tables from `schema.sql`
- [ ] 1.2 Implement `src/ingest/excel_parser.py` - multi-sheet parser, header detection, merged-cell forward-fill
- [ ] 1.3 Implement `src/ingest/pdf_parser.py` - PyMuPDF block extraction with page numbers and bounding boxes
- [ ] 1.4 Implement `src/ingest/ocr.py` - pytesseract fallback for scanned pages
- [ ] 1.5 Write `scripts/generate_sample_data.py` - sample Excel and sample vendor PDFs

## Phase 2: Multi-Agent Council Evaluation
- [ ] 2.1 Write prompts in `src/engine/prompts.py`
- [ ] 2.2 Implement `src/engine/agents.py`
- [ ] 2.3 Implement `src/engine/judge.py`
- [ ] 2.4 Implement `src/engine/orchestrator.py`
- [ ] 2.5 Implement `src/app/run_pipeline.py`

## Phase 3: Human-in-the-Loop Review UI
- [ ] 3.1 Implement `src/ui/review_app.py`
- [ ] 3.2 Add sidebar filters
- [ ] 3.3 Add summary stats

## Phase 4: Excel Report Generation
- [ ] 4.1 Implement `src/reporting/excel_report.py`
- [ ] 4.2 Ensure downloadable report path

## Phase 5: FastAPI Backend
- [ ] 5.1 Implement `src/app/api.py`
- [ ] 5.2 Add JWT auth to API

## Phase 6: Config & Hardening
- [ ] 6.1 Write `config/settings.yaml`
- [ ] 6.2 Write `requirements.txt`
- [ ] 6.3 Write bootstrap scripts
- [ ] 6.4 Write `README.md`

## Phase 7: Testing
- [ ] 7.1 Add parser tests
- [ ] 7.2 Add PDF parser tests
- [ ] 7.3 Add heuristic agent tests
- [ ] 7.4 Add pipeline test
- [ ] 7.5 Add report tests
