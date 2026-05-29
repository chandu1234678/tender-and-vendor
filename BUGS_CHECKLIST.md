# Bug Checklist and Tracking

Legend: - [ ] Open  - [x] Resolved

| ID | Severity | File | Short description | Status |
|---:|---|---|---|:---:|
| 1 | Critical | `src/engine/orchestrator.py` | _trim_context set to 900 chars (should be ~3500) | [ ] |
| 2 | Critical | `src/evaluator.py` | _increment_hit opens SQLite per sentence (many connections) | [ ] |
| 3 | Critical | `src/engine/orchestrator.py` | VendorIndex frozen=True but contains mutable lists | [ ] |
| 4 | Critical | `src/engine/ollama_client.py` | _generate_lmstudio ignores max_tokens | [ ] |
| 5 | Critical | `src/engine/ollama_client.py` | _extract_lmstudio_text misses 'message' blocks | [ ] |
| 6 | Critical | `src/evaluator.py` | retrain_from_feedback creates single-token heuristic rules | [ ] |
| 7 | Serious | `src/engine/orchestrator.py` | dispatch_spec_vendor returns incompatible result shapes | [ ] |
| 8 | Serious | `src/engine/orchestrator.py` | _numeric_magnitude_ok returns True when unit not found | [ ] |
| 9 | Serious | `src/engine/ollama_client.py` | is_healthy() caches permanently (no TTL) | [ ] |
| 10 | Serious | `src/engine/ollama_client.py` | LRU cache race causes duplicate LLM calls under concurrency | [ ] |
| 11 | Serious | `src/reporting/excel_report.py` | company_requirement casing mismatch | [ ] |
| 12 | Serious | `src/reporting/excel_report.py` | _find_compliance_cols assumes triplets | [ ] |
| 13 | Structural | `src/evaluator.py` & `src/engine/orchestrator.py` | Two parallel evaluation stacks active | [ ] |
| 14 | Structural | `requirements.txt` | Unpinned package versions | [ ] |
| 15 | Structural | `config/settings.yaml` | Hardcoded LAN IP for LLM host | [ ] |
| 16 | Duplicate | `src/engine/orchestrator.py` | Duplicate of #3 (VendorIndex) | [ ] |
| 17 | Structural | `run_pipeline.py` | FAST_REUSE_PARSED in docs but not implemented | [ ] |
| 18 | Structural | `src/engine/orchestrator.py` | _quick_evidence_verdict uses only top-1 block | [ ] |
| 19 | Structural | `src/engine/ollama_client.py` | Uses /api/v1/chat instead of /v1/chat/completions | [ ] |
| 20 | Structural | `src/evaluator.py` | retrain_from_feedback has no UPDATE path | [ ] |
| 21 | Critical | `src/ui/review_app.py` | Override UPDATE has no rowcount check | [ ] |
| 22 | Critical | `src/ui/review_app.py` | Transaction rollback can silently undo override | [ ] |
| 23 | Critical | `src/storage/schema.sql` | heuristic_rules missing UNIQUE constraint | [ ] |
| 24 | Critical | `src/storage/db.py` | _ensure_column uses f-strings for SQL identifiers | [ ] |
| 25 | Critical | `src/app/run_pipeline.py` | _citation_doc_id always uses :0 index | [ ] |
| 26 | Serious | `src/reporting/excel_report.py` | vendor_data lookup compares wrong variable names | [ ] |
| 27 | Serious | `src/ingest/pdf_parser.py` | 2-column PDFs not handled; ordering scrambled | [ ] |
| 28 | Serious | `src/storage/db.py` | format_profiles index not ensured at init | [ ] |
| 29 | Serious | `src/engine/agents.py` | Heuristic evaluator has import-time side effects | [ ] |
| 30 | Serious | `src/engine/judge.py` | Judge prompt receives unlabeled agent outputs | [ ] |
| 31 | Serious | `src/ingest/ocr.py` | OCR runs on every page even for digital PDFs | [ ] |
| 32 | Serious | `src/ui/review_app.py` | PDF viewer path resolution breaks if file moved | [ ] |
| 33 | Serious | `src/engine/orchestrator.py` | Confidence calibration inverted for NO vs YES | [ ] |
| 34 | Serious | `src/ingest/excel_parser.py` | ffill on df.iloc may be a no-op in pandas 2.x | [ ] |
| 35 | Structural | `src/app/run_pipeline.py` | Block order alignment between DB and VendorIndex fragile | [ ] |
| 36 | Structural | `tests/test_pipeline.py` | Duplicate dict key in test fixture | [ ] |
| 37 | Structural | `src/app/api.py` | /reset-pipeline documented but missing | [ ] |
| 38 | Serious | `src/engine/ollama_client.py` | system_prompt sent as wrong key to LM Studio | [ ] |
| 39 | Serious | `src/app/api.py` | Override actions not logged to audit_log | [ ] |
| 40 | Critical | `src/storage/db.py` | Seed heuristic rules cause negation false positives | [ ] |
| 41 | Structural | `src/engine/format_detector.py` | Format profiles re-saved every run (no hash check) | [ ] |
| 42 | Structural | `src/ui/review_app.py` | Loads entire compliance_matrix on every render | [ ] |
| 43 | Serious | `tests/test_engine_agents.py` | Monkeypatch targets obsolete name; tests not isolating | [ ] |
| 44 | Structural | `src/engine/orchestrator.py` | Numeric extraction may pick numbers from 16:9 aspect ratios | [ ] |
| 45 | Critical | `src/app/api.py` | Dead code after return; /report endpoint missing | [ ] |
| 46 | Critical | `src/app/run_pipeline.py` | Connection leak: get_connection() result not closed | [ ] |
| 47 | Critical | `src/app/run_pipeline.py` | FAST_REUSE_PARSED blocks lose doc_id (missing doc_id in SELECT) | [ ] |
| 48 | Critical | `src/app/api.py` | Upload_files leaves partial files on disk when size limit exceeded | [ ] |
| 49 | Serious | `src/app/run_pipeline.py` | _update_progress commits on every pair (fsync storm) | [ ] |
| 50 | Serious | `src/app/run_pipeline.py` | Logging references eval_workers before it's assigned | [ ] |
| 51 | Serious | `src/engine/format_detector.py` | Keyword 'spec' overmatches substrings | [ ] |
| 52 | Serious | `src/engine/format_detector.py` | FormatProfile.from_dict mutates input dict | [ ] |
| 53 | Serious | `src/engine/agents.py` | default_model() called at import time; stale model_name | [ ] |
| 54 | Serious | `src/app/run_pipeline.py` | ThreadPoolExecutor shares single SQLite connection across threads | [ ] |

---

To update status: edit this file and replace `[ ]` with `[x]` for resolved items.

