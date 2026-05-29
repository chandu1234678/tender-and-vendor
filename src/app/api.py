import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict

from src.app.run_pipeline import main as run_pipeline_main
from src.storage.db import get_connection, init_db
from src.utils.paths import PROJECT_ROOT

from contextlib import asynccontextmanager


def _warm_ollama() -> None:
    """Warm the local Ollama model without blocking API startup."""
    if os.environ.get("OLLAMA_WARMUP", "1").strip().lower() not in {"1", "true", "yes"}:
        return
    try:
        from src.engine.ollama_client import default_model, ollama_generate

        model = default_model()
        ollama_generate(
            model,
            'Return only this JSON: {"status":"YES","citation":"warmup","reasoning":"warmup","confidence":1.0}',
            temperature=0.0,
            max_tokens=40,
        )
    except Exception:
        pass


@asynccontextmanager
async def _lifespan(application: FastAPI):
    """Clear any stale running/queued pipeline runs on startup."""
    try:
        _ensure_app_db()
        conn = get_connection(str(_db_path()))
        try:
            conn.execute(
                "UPDATE pipeline_runs SET status='failed', message='Interrupted — server restarted', "
                "updated_at=CURRENT_TIMESTAMP WHERE status IN ('running', 'queued')"
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    threading.Thread(target=_warm_ollama, daemon=True).start()
    yield


app = FastAPI(title="Vendor Comparison Platform", lifespan=_lifespan)

# ---------------------------------------------------------------------------
# Network / CORS configuration
# Read ALLOWED_HOSTS from env (comma-separated IPs/hostnames).
# Defaults to localhost-only. Set to the machine's LAN IP to allow network access.
# Example:  ALLOWED_HOSTS=10.5.51.82
# ---------------------------------------------------------------------------
_ALLOWED_HOSTS: set[str] = {"127.0.0.1", "::1", "localhost"}
_env_hosts = os.environ.get("ALLOWED_HOSTS", "")
for _h in _env_hosts.split(","):
    _h = _h.strip()
    if _h:
        _ALLOWED_HOSTS.add(_h)

# Build CORS origin list from allowed hosts
_CORS_ORIGINS: list[str] = []
for _h in _ALLOWED_HOSTS:
    for _port in ("", ":5173", ":8088", ":8501"):
        _CORS_ORIGINS.append(f"http://{_h}{_port}")
        _CORS_ORIGINS.append(f"https://{_h}{_port}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(set(_CORS_ORIGINS)),
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".xlsx"}


class HealthResponse(BaseModel):
    status: str


class UploadResponse(BaseModel):
    saved: list[str]


class PipelineRunResponse(BaseModel):
    run_id: str
    status: str


class PipelineStatusResponse(BaseModel):
    run_id: str
    status: str
    progress: float
    message: str
    error: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FileInfo(BaseModel):
    file_name: str
    extension: str
    size_bytes: int
    modified_at: str
    role: str


class FilesResponse(BaseModel):
    incoming: list[FileInfo]


class ResultsResponse(BaseModel):
    results: list[dict[str, Any]]
    count: int
    limit: int
    offset: int


class SummaryResponse(BaseModel):
    total_results: int
    status_counts: dict[str, int]
    vendor_counts: dict[str, int]
    spec_counts: dict[str, int]


class ParsedDocumentResponse(BaseModel):
    doc_id: str
    file_name: str
    page: int
    bbox: str
    text: str


class OverrideRequest(BaseModel):
    spec_id: str = Field(..., min_length=1)
    vendor_id: str = Field(..., min_length=1)
    new_status: str = Field(..., min_length=1)
    justification: str = Field(..., min_length=1)


class OverrideResponse(BaseModel):
    status: str
    spec_id: str
    vendor_id: str
    new_status: str


def require_localhost(request: Request) -> None:
    """Allow requests from any host in _ALLOWED_HOSTS, or any RFC-1918 LAN address.

    RFC-1918 private ranges:
      10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
    This keeps the API air-gapped (no public internet access) while allowing
    all machines on the local network without needing to enumerate every IP.
    """
    host = request.client.host if request.client else ""

    # always allow explicit allowlist
    if host in _ALLOWED_HOSTS:
        return

    # allow any private LAN address
    import ipaddress
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback:
            return
    except ValueError:
        pass  # not a valid IP — fall through to deny

    raise HTTPException(status_code=403, detail=f"Access denied from {host}")


def get_current_user(request: Request) -> Dict[str, Any]:
    """Return a minimal user dict. In production, validate a JWT or session token.

    For the local air-gapped deployment this simply returns an anonymous admin
    user so the API remains functional without a full auth stack.
    """
    return {"username": "admin", "full_name": "Administrator", "disabled": False}


def _db_path() -> Path:
    return PROJECT_ROOT / "data" / "parsed" / "app.db"


def _safe_output_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", name.strip())
    return cleaned or "file"


def _latest_summary_report() -> Path:
    output_dir = PROJECT_ROOT / "data" / "output"
    candidates = sorted(
        output_dir.glob("vendor_comparison_matrix*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return output_dir / "vendor_comparison_matrix.xlsx"


def _latest_vendor_report(vendor_id: str) -> Path:
    output_dir = PROJECT_ROOT / "data" / "output"
    safe_name = _safe_output_name(Path(vendor_id).name)
    candidates = sorted(
        output_dir.glob(f"vendor_{safe_name}*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return output_dir / f"vendor_{safe_name}.xlsx"


def _output_file_path(file_name: str) -> Path:
    output_dir = PROJECT_ROOT / "data" / "output"
    safe_name = Path(file_name).name
    file_path = output_dir / safe_name
    try:
        if not file_path.exists():
            raise FileNotFoundError
        if file_path.resolve().parent != output_dir.resolve():
            raise FileNotFoundError
    except OSError:
        raise HTTPException(status_code=404, detail=f"Output file not found: {file_name}")
    return file_path


def _report_path() -> Path:
    return _latest_summary_report()


def _incoming_dir() -> Path:
    return PROJECT_ROOT / "data" / "incoming"


def _ensure_app_db() -> None:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db(str(db_path))


def _dict_rows(conn, query: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn.row_factory = lambda cursor, row: {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
    return conn.execute(query, params).fetchall()


def _pipeline_run_from_row(row) -> dict[str, Any]:
    return {
        "run_id": row[0],
        "status": row[1],
        "progress": row[2],
        "message": row[3],
        "error": row[4],
        "created_at": row[5],
        "updated_at": row[6],
    }


def _file_role(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "vendor_pdf"
    if suffix in {".xlsx", ".xlsm"}:
        return "master_workbook"
    return "unsupported"


def _file_info(path: Path) -> FileInfo:
    stat = path.stat()
    return FileInfo(
        file_name=path.name,
        extension=path.suffix.lower(),
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
        role=_file_role(path),
    )


def _set_run_state(run_id: str, status_value: str, message: str = "", progress: float = 0.0, error: str = "") -> None:
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        conn.execute(
            "UPDATE pipeline_runs SET status=?, message=?, progress=?, error=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
            (status_value, message, progress, error, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _run_pipeline_job(run_id: str) -> None:
    try:
        _set_run_state(run_id, "running", "Pipeline started", 0.0)
        # Always reuse parsed PDF blocks — keeps LLM warm-up fast and avoids
        # re-parsing PDFs that haven't changed.
        os.environ.setdefault("FAST_REUSE_PARSED", "1")
        run_pipeline_main(run_id=run_id)
        _set_run_state(run_id, "completed", "Pipeline completed", 100.0)
    except Exception as exc:
        _set_run_state(run_id, "failed", "Pipeline failed", 0.0, str(exc))


@app.get("/health", response_model=HealthResponse)
def health(_: None = Depends(require_localhost)) -> dict:
    return {"status": "ok"}


@app.get("/ollama-status")
def ollama_status_endpoint(_: None = Depends(require_localhost)) -> dict:
    """Check Ollama connectivity and return available models."""
    from src.engine.ollama_client import (
        LLM_BACKEND,
        OLLAMA_HOST,
        default_model,
        is_healthy,
        list_models,
    )
    healthy = is_healthy()
    models = list_models() if healthy else []
    return {
        "healthy": healthy,
        "host": OLLAMA_HOST,
        "backend": LLM_BACKEND,
        "models": models,
        "selected_model": default_model() if healthy else None,
    }


@app.get("/me")
def me_endpoint(
    _: None = Depends(require_localhost),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    return current_user


@app.get("/files", response_model=FilesResponse)
def files_endpoint(_: None = Depends(require_localhost)) -> dict:
    incoming = _incoming_dir()
    incoming.mkdir(parents=True, exist_ok=True)
    files = [
        _file_info(path)
        for path in sorted(incoming.iterdir(), key=lambda item: item.name.lower())
        if path.is_file()
    ]
    return {"incoming": files}


@app.delete("/files/{file_name}")
def delete_incoming_file(file_name: str, _: None = Depends(require_localhost)) -> dict:
    """Remove a file from data/incoming so it won't be picked up by the next pipeline run."""
    safe_name = Path(file_name).name          # strip any path traversal
    target = _incoming_dir() / safe_name
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {safe_name}")
    if not target.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {safe_name}")
    # Prevent deleting the master workbook while a pipeline is running
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        active = conn.execute(
            "SELECT run_id FROM pipeline_runs WHERE status IN ('queued','running') LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if active:
        raise HTTPException(status_code=409, detail="Cannot delete files while pipeline is running")
    target.unlink()
    return {"deleted": safe_name}


@app.post("/upload", response_model=UploadResponse)
def upload_files(files: list[UploadFile] = File(...), _: None = Depends(require_localhost)) -> dict:
    incoming = PROJECT_ROOT / "data" / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    names = [Path(upload.filename).name for upload in files]
    workbook_count = sum(1 for name in names if Path(name).suffix.lower() == ".xlsx")
    pdf_count = sum(1 for name in names if Path(name).suffix.lower() == ".pdf")
    if workbook_count != 1 or pdf_count < 1:
        raise HTTPException(status_code=400, detail="Upload exactly one .xlsx workbook and at least one .pdf vendor file")
    saved = []
    for upload in files:
        dest_name = Path(upload.filename).name
        if Path(dest_name).suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {dest_name}")
        destination = incoming / dest_name
        size = 0
        with destination.open("wb") as target:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_MB} MB)")
                target.write(chunk)
        saved.append(destination.name)
    return {"saved": saved}


@app.post("/run-pipeline", response_model=PipelineRunResponse)
def run_pipeline_endpoint(_: None = Depends(require_localhost)) -> dict:
    _ensure_app_db()
    run_id = str(uuid.uuid4())
    conn = get_connection(str(_db_path()))
    try:
        active = conn.execute(
            "SELECT run_id FROM pipeline_runs WHERE status IN ('queued', 'running') ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if active:
            raise HTTPException(status_code=409, detail=f"Pipeline already active: {active[0]}")

        # ── Fresh run: clear compliance results for all current incoming vendors ──
        # PDF parse cache (parsed_documents) is intentionally kept so re-parsing
        # is skipped and the LLM warms up faster on the next run.
        incoming = _incoming_dir()
        current_vendors = [p.stem for p in incoming.glob("*.pdf")]
        if current_vendors:
            placeholders = ",".join("?" * len(current_vendors))
            deleted = conn.execute(
                f"DELETE FROM compliance_matrix WHERE vendor_id IN ({placeholders})",
                current_vendors,
            ).rowcount
            if deleted:
                conn.execute(
                    "INSERT INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
                    ("fresh_run_clear", "compliance_matrix", run_id,
                     json.dumps({"vendors": current_vendors, "rows_cleared": deleted})),
                )

        conn.execute(
            "INSERT OR REPLACE INTO pipeline_runs (run_id, status, progress, message, error, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (run_id, "queued", 0.0, "Queued", ""),
        )
        conn.commit()
    finally:
        conn.close()

    thread = threading.Thread(target=_run_pipeline_job, args=(run_id,), daemon=True)
    thread.start()
    return {"run_id": run_id, "status": "queued"}


@app.post("/reset-pipeline")
def reset_pipeline_endpoint(_: None = Depends(require_localhost)) -> dict:
    """Mark any stuck running/queued pipeline runs as failed so a new run can start."""
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        conn.execute(
            "UPDATE pipeline_runs SET status='failed', message='Reset by operator', "
            "updated_at=CURRENT_TIMESTAMP WHERE status IN ('running', 'queued')"
        )
        conn.commit()
        cleared = conn.execute("SELECT changes()").fetchone()[0]
    finally:
        conn.close()
    return {"status": "ok", "cleared": cleared}


@app.get("/runs", response_model=list[PipelineStatusResponse])
def runs_endpoint(
    limit: int = 25,
    offset: int = 0,
    _: None = Depends(require_localhost),
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        rows = conn.execute(
            """
            SELECT run_id, status, progress, message, error, created_at, updated_at
            FROM pipeline_runs
            ORDER BY datetime(updated_at) DESC, datetime(created_at) DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    finally:
        conn.close()
    return [_pipeline_run_from_row(row) for row in rows]


@app.get("/runs/{run_id}", response_model=PipelineStatusResponse)
def run_detail_endpoint(run_id: str, _: None = Depends(require_localhost)) -> dict:
    return status_endpoint(run_id, _)


@app.get("/status/{run_id}", response_model=PipelineStatusResponse)
def status_endpoint(run_id: str, _: None = Depends(require_localhost)) -> dict:
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        row = conn.execute(
            "SELECT run_id, status, progress, message, error, created_at, updated_at FROM pipeline_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return _pipeline_run_from_row(row)


@app.get("/results", response_model=ResultsResponse)
def results_endpoint(
    vendor_id: Optional[str] = None,
    spec_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 500,
    offset: int = 0,
    _: None = Depends(require_localhost),
) -> dict:
    limit = max(1, min(limit, 5000))
    offset = max(0, offset)
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        clauses = []
        params: list[Any] = []
        if vendor_id:
            clauses.append("vendor_id=?")
            params.append(vendor_id)
        if spec_id:
            clauses.append("spec_id=?")
            params.append(spec_id)
        if status_filter:
            clauses.append("status=?")
            params.append(status_filter)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        count = conn.execute(f"SELECT COUNT(*) FROM compliance_matrix {where_sql}", tuple(params)).fetchone()[0]
        rows = _dict_rows(
            conn,
            f"SELECT * FROM compliance_matrix {where_sql} ORDER BY spec_id, vendor_id LIMIT ? OFFSET ?",
            tuple(params + [limit, offset]),
        )
    finally:
        conn.close()
    return {"results": rows, "count": count, "limit": limit, "offset": offset}


@app.get("/summary", response_model=SummaryResponse)
def summary_endpoint(_: None = Depends(require_localhost)) -> dict:
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        total_results = conn.execute("SELECT COUNT(*) FROM compliance_matrix").fetchone()[0]
        status_counts = dict(conn.execute("SELECT status, COUNT(*) FROM compliance_matrix GROUP BY status").fetchall())
        vendor_counts = dict(conn.execute("SELECT vendor_id, COUNT(*) FROM compliance_matrix GROUP BY vendor_id").fetchall())
        spec_counts = dict(conn.execute("SELECT spec_id, COUNT(*) FROM compliance_matrix GROUP BY spec_id").fetchall())
    finally:
        conn.close()
    return {
        "total_results": total_results,
        "status_counts": status_counts,
        "vendor_counts": vendor_counts,
        "spec_counts": spec_counts,
    }


@app.get("/parsed-document/{doc_id}", response_model=ParsedDocumentResponse)
def parsed_document_endpoint(doc_id: str, _: None = Depends(require_localhost)) -> dict:
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        row = conn.execute(
            "SELECT doc_id, file_name, page, bbox, text FROM parsed_documents WHERE doc_id=?",
            (doc_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Parsed document not found")
    return {
        "doc_id": row[0],
        "file_name": row[1],
        "page": row[2],
        "bbox": row[3],
        "text": row[4],
    }


@app.get("/pdf/{file_name}")
def pdf_endpoint(file_name: str, _: None = Depends(require_localhost)):
    pdf_path = _incoming_dir() / Path(file_name).name
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(str(pdf_path), media_type="application/pdf", filename=pdf_path.name)


@app.get("/audit-log")
def audit_log_endpoint(
    limit: int = 100,
    offset: int = 0,
    _: None = Depends(require_localhost),
) -> dict:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        rows = _dict_rows(
            conn,
            """
            SELECT id, action, entity_type, entity_id, details, created_at
            FROM audit_log
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
    finally:
        conn.close()
    return {"events": rows, "count": count, "limit": limit, "offset": offset}


@app.get("/training-queue")
def training_queue_endpoint(
    processed: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    _: None = Depends(require_localhost),
) -> dict:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        clauses = []
        params: list[Any] = []
        if processed is not None:
            clauses.append("processed=?")
            params.append(1 if processed else 0)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        count = conn.execute(f"SELECT COUNT(*) FROM training_queue {where_sql}", tuple(params)).fetchone()[0]
        rows = _dict_rows(
            conn,
            f"""
            SELECT id, spec_id, vendor_id, doc_id, page, bbox, excerpt, label, processed, created_at
            FROM training_queue
            {where_sql}
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
    finally:
        conn.close()
    return {"items": rows, "count": count, "limit": limit, "offset": offset}


@app.post("/override", response_model=OverrideResponse)
def override_endpoint(payload: OverrideRequest, _: None = Depends(require_localhost)) -> dict:
    spec_id = payload.spec_id.strip()
    vendor_id = payload.vendor_id.strip()
    new_status = payload.new_status.strip()
    justification = payload.justification.strip()
    if not spec_id or not vendor_id or not new_status or not justification:
        raise HTTPException(status_code=400, detail="spec_id, vendor_id, new_status, and justification are required")

    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        row = conn.execute(
            "SELECT status, citation_doc_id, citation_excerpt FROM compliance_matrix WHERE spec_id=? AND vendor_id=?",
            (spec_id, vendor_id),
        ).fetchone()
        original = row[0] if row else "UNKNOWN"
        citation_doc_id = row[1] if row and len(row) > 1 else None
        citation_excerpt = row[2] if row and len(row) > 2 and row[2] else ""
        conn.execute(
            "UPDATE compliance_matrix SET status=?, reasoning=? WHERE spec_id=? AND vendor_id=?",
            (new_status, f"[OVERRIDE] {justification}", spec_id, vendor_id),
        )
        conn.execute(
            "INSERT INTO autonomous_feedback_loop (spec_id, vendor_id, original_status, corrected_status, justification, context) VALUES (?, ?, ?, ?, ?, ?)",
            (spec_id, vendor_id, original, new_status, justification, citation_excerpt),
        )
        if citation_doc_id:
            pdrow = conn.execute(
                "SELECT page, bbox, text FROM parsed_documents WHERE doc_id=?",
                (citation_doc_id,),
            ).fetchone()
            page = pdrow[0] if pdrow else None
            bbox = pdrow[1] if pdrow else None
            excerpt = pdrow[2] if pdrow else citation_excerpt
            conn.execute(
                "INSERT INTO training_queue (spec_id, vendor_id, doc_id, page, bbox, excerpt, label) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (spec_id, vendor_id, citation_doc_id, page, bbox, excerpt, new_status),
            )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "spec_id": spec_id, "vendor_id": vendor_id, "new_status": new_status}


@app.post("/retrain")
def retrain_endpoint(_: None = Depends(require_localhost)) -> dict:
    """Process unprocessed training_queue rows and extract new heuristic rules.

    This is the human-in-the-loop retraining trigger.  Call it after applying
    overrides to immediately improve the heuristic evaluator for the next run.
    """
    from src.evaluator import retrain_from_feedback
    _ensure_app_db()
    added = retrain_from_feedback(db_path=str(_db_path()))
    # also log to audit
    conn = get_connection(str(_db_path()))
    try:
        conn.execute(
            "INSERT INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
            ("retrain", "heuristic_rules", "manual", json.dumps({"new_rules": added})),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "new_rules_added": added}


@app.get("/heuristic-rules")
def heuristic_rules_endpoint(
    limit: int = 200,
    offset: int = 0,
    _: None = Depends(require_localhost),
) -> dict:
    """List all heuristic rules currently in use."""
    limit = max(1, min(limit, 500))
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        count = conn.execute("SELECT COUNT(*) FROM heuristic_rules").fetchone()[0]
        rows = _dict_rows(
            conn,
            "SELECT id, rule_type, pattern, verdict, weight, hit_count, source, created_at "
            "FROM heuristic_rules ORDER BY weight DESC, hit_count DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    finally:
        conn.close()
    return {"rules": rows, "count": count}


@app.post("/heuristic-rules")
def add_heuristic_rule_endpoint(
    payload: dict,
    _: None = Depends(require_localhost),
) -> dict:
    """Manually add a heuristic rule."""
    pattern = str(payload.get("pattern", "")).strip().lower()
    verdict = str(payload.get("verdict", "")).strip().upper()
    weight = float(payload.get("weight", 1.0))
    if not pattern or verdict not in {"YES", "NO", "NEARLY OK"}:
        raise HTTPException(status_code=400, detail="pattern and verdict (YES/NO/NEARLY OK) required")
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO heuristic_rules (rule_type, pattern, verdict, weight, source) "
            "VALUES ('keyword', ?, ?, ?, 'manual')",
            (pattern, verdict, weight),
        )
        conn.execute(
            "INSERT INTO audit_log (action, entity_type, entity_id, details) VALUES (?, ?, ?, ?)",
            ("add_rule", "heuristic_rules", pattern, json.dumps({"verdict": verdict, "weight": weight})),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "pattern": pattern, "verdict": verdict}


@app.get("/format-profiles")
def format_profiles_endpoint(_: None = Depends(require_localhost)) -> dict:
    """List all detected format profiles (one per workbook sheet)."""
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        rows = _dict_rows(
            conn,
            "SELECT file_name, sheet_name, profile_json, created_at FROM format_profiles "
            "ORDER BY file_name, sheet_name",
        )
    finally:
        conn.close()
    return {"profiles": rows, "count": len(rows)}

    report_path = _report_path()
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(str(report_path), filename=report_path.name)


@app.get("/output-files")
def output_files_endpoint(_: None = Depends(require_localhost)) -> dict:
    """List all generated output files available for download."""
    out_dir = PROJECT_ROOT / "data" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(out_dir.iterdir()):
        if path.is_file() and path.suffix.lower() == ".xlsx":
            stat = path.stat()
            files.append({
                "file_name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    return {"files": files}


@app.get("/output/{file_name}")
def output_file_endpoint(file_name: str, _: None = Depends(require_localhost)):
    output_path = _output_file_path(file_name)
    return FileResponse(str(output_path), filename=output_path.name)


@app.get("/report/vendor/{vendor_id}")
def vendor_report_endpoint(vendor_id: str, _: None = Depends(require_localhost)):
    """Download the per-vendor compliance file."""
    safe_name = Path(vendor_id).name  # strip any path traversal
    vendor_path = _latest_vendor_report(safe_name)
    if not vendor_path.exists():
        raise HTTPException(status_code=404, detail=f"Vendor report not found: vendor_{safe_name}.xlsx")
    return FileResponse(str(vendor_path), filename=vendor_path.name)


@app.get("/report/all")
def all_reports_endpoint(_: None = Depends(require_localhost)):
    """Download a ZIP archive containing every generated output file."""
    import io
    import zipfile

    out_dir = PROJECT_ROOT / "data" / "output"
    xlsx_files = [p for p in out_dir.iterdir() if p.is_file() and p.suffix.lower() == ".xlsx"]
    if not xlsx_files:
        raise HTTPException(status_code=404, detail="No output files found. Run the pipeline first.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(xlsx_files):
            zf.write(p, arcname=p.name)
    buf.seek(0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=compliance_reports.zip"},
    )

