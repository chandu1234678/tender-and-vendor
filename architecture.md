# Architecture (Production)

## Core Stages
1) Ingestion and Decomposition
- Parse PDFs and Excel.
- Preserve layout blocks and table structure.
- Persist parsed blocks with coordinates.

2) Multi-Agent Evaluation
- Orchestrator slices context by spec.
- Agents: Technical, Risk, Fallback.
- Consensus Judge validates citations and decides verdict.

3) Human Review
- Review grid with citations.
- Overrides captured with justification.

4) Reporting
- Excel matrix with best-vendor ranking.
- Summary sheet and audit log export.

## Data Stores
- parsed_documents: raw blocks + coordinates.
- compliance_matrix: verdicts and citations.
- autonomous_feedback_loop: overrides for learning.

## Non-Functional Targets
- Air-gapped operation.
- Deterministic verdicts at temp 0.0.
- Traceable citations for every verdict.
- Recoverable runs via transactional writes.
