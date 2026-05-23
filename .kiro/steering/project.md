# Project: Tender & Vendor Compliance Platform

## What This Is
A 100% local, air-gapped, Python-based platform that automates government procurement compliance auditing for company.

## Core Problem
- A engineer receives 1 master spec Excel and up to 10 vendor PDF proposals.
- The engineer must manually cross-check every spec row against every vendor PDF and mark YES / NO / NEARLY OK.
- This takes days; the platform reduces it to minutes while preserving citations and reviewability.

## Output
A color-coded Excel matrix with verbatim citations and page numbers, plus a Summary sheet with vendor ranking and best-vendor recommendation.

## Architecture
- Python 3.11+
- PDF parsing: PyMuPDF
- Excel parsing: pandas + openpyxl
- OCR fallback: pytesseract
- AI evaluation: Ollama if available, deterministic heuristic fallback otherwise
- State: SQLite with WAL, foreign keys, and secure_delete
- UI: Streamlit review console
- API: FastAPI for pipeline triggering and status
- Report: openpyxl styled Excel with Matrix, Details, Summary sheets
- Zero network egress

## Database Tables
- parsed_documents
- master_specs
- compliance_matrix
- autonomous_feedback_loop
- training_queue
- audit_log
- pipeline_runs

## Non-Negotiables
1. No data leaves the machine.
2. Every verdict has a verbatim citation from the vendor PDF.
3. All DB writes are transactional.
4. Streamlit supports human override with justification capture.
5. Excel output is color-coded and downloadable.
6. Support up to 50 spec rows by 10 vendor PDFs in a single run.
7. Heuristic fallback always works without Ollama.
