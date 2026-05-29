# Best Stack Plan (Vendor Comparison Platform)

## Purpose
Build an air-gapped, production-grade system to compare 10 vendors against a master specification matrix, produce YES/NEARLY OK/NO with citations, and select best vendor per spec and overall.

## Assumptions (confirm or edit)
- Air-gapped deployment with no internet egress.
- Inputs: master spec in Excel, vendor submissions in PDF and Excel.
- Target: 10 vendors per run, 50 to 200 specs per project.
- Users: procurement officers and engineers; need review and override.
- Output: Excel matrix with citations and summary report.

## Recommended Stack (best balance: accuracy, security, maintainability)

### Core Language and Runtime
- Python 3.11 for ingestion, evaluation, and reporting.

### Model Runtime (local only)
- Ollama for local LLM serving.
- Default model: Llama 3.x Instruct (8B or 70B based on hardware).

### Ingestion and Parsing
- PyMuPDF for PDF text and layout blocks.
- pdfplumber as fallback for table-heavy PDFs.
- pytesseract + local Tesseract for scanned PDFs (OCR).
- pandas + openpyxl for Excel I/O.

### Orchestration and API
- FastAPI for the local service layer.
- SQLite for local transactional state; Postgres if multi-user server.

### UI
- Streamlit for internal review and override (fast to deliver).
- Excel output for procurement team workflows.

### Storage
- Local filesystem for raw files and extracted text cache.
- SQLite or Postgres for audit logs and override history.

### Packaging and Deployment
- Docker or Podman for on-prem server deployments.
- Bare-metal install for single workstation setups.

## Component Architecture

1) Ingestion Service
- Watches a secure folder for new files.
- Extracts text blocks with coordinates.
- Normalizes tables into text matrices.
- Stores parsed blocks and metadata in the database.

2) Evaluation Engine
- Per spec, selects relevant chunks (layout-aware retrieval).
- Runs multi-agent prompts: strict auditor, fallback finder, consensus judge.
- Produces JSON with status, citation, and reasoning.
- Writes results to compliance_matrix table.

3) Human Review Console
- Shows matrix with color coding and citations.
- Allows manual overrides with justification.
- Logs overrides for continuous learning.

4) Report Generator
- Builds final Excel matrix with formatting.
- Produces a summary sheet and best-vendor ranking.

## Data Flow (high level)
- Master spec Excel + vendor PDFs/Excel -> Ingestion -> Parsed cache

- Parsed cache + spec -> Evaluation -> Compliance matrix
- Compliance matrix + overrides -> Report generator -> Excel output

## Security Controls
- Block all outbound traffic for Python and Ollama processes.
- No cloud services or external APIs.
- File system permissions for secure folders.
- Database encryption at rest if policy requires.
- Immutable audit logs for overrides.

## Continuous Learning (air-gapped)
- Store all overrides in a correction table.
- Quarterly export to JSONL for local fine-tuning.
- Swap in updated local models after evaluation.

## Hardware Guidance
- 8B model: 16 GB RAM, CPU or small GPU.
- 70B model: 64 GB RAM, 24 GB+ VRAM GPU recommended.
- SSD storage for fast parsing and model loading.

## Phased Delivery Plan

Phase 1: Foundations (2 to 4 weeks)
- Ingestion pipeline for PDF and Excel.
- SQLite schema for parsed_docs and compliance_matrix.
- Basic evaluation prompt and JSON output.
- Excel report generation.

Phase 2: Accuracy and Review (3 to 5 weeks)
- Multi-agent evaluation with consensus judge.
- Review UI with overrides and audit logging.
- Chunk selection improvements with layout-aware retrieval.

Phase 3: Production Hardening (4 to 6 weeks)
- RBAC and user audit trails.
- Data retention rules and encryption at rest.
- Containerized deployment or signed installer.
- Monitoring, health checks, and error recovery.

Phase 4: Continuous Learning (ongoing)
- Override export pipeline.
- Local fine-tuning workflow and model upgrade plan.

## Key Risks and Mitigations
- OCR quality on scanned PDFs -> add manual correction step and fallback parsing.
- Hallucinated citations -> enforce citation extraction from parsed blocks only.
- Large context overflow -> use chunked retrieval with strict max token limits.

## Open Items (need confirmation)
- Final deployment target (workstation vs server).
- Exact document types and volumes.
- Preferred model size and available hardware.
- Compliance and audit requirements.
