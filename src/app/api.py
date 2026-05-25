import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import jwt
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status, Request
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext

from src.app.run_pipeline import main as run_pipeline_main
from src.storage.db import get_connection, init_db
from src.utils.paths import PROJECT_ROOT

app = FastAPI(title="Vendor Comparison Platform")
LOCAL_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:8501",
    "http://127.0.0.1:8501",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".xlsx"}

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


fake_users_db = {
    "admin": {
        "username": "admin",
        "full_name": "Administrator",
        "hashed_password": get_password_hash("changeme"),
        "disabled": False,
    }
}


def authenticate_user(username: str, password: str) -> Optional[dict]:
    user = fake_users_db.get(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub") or payload.get("username")
        if username is None:
            raise credentials_exception
    except Exception:
        raise credentials_exception
    user = fake_users_db.get(username)
    if user is None:
        raise credentials_exception
    return user


def require_localhost(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Localhost access only")


def _db_path() -> Path:
    return PROJECT_ROOT / "data" / "parsed" / "app.db"


def _report_path() -> Path:
    return PROJECT_ROOT / "data" / "output" / "vendor_comparison_matrix.xlsx"


def _incoming_dir() -> Path:
    return PROJECT_ROOT / "data" / "incoming"


def _ensure_app_db() -> None:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db(str(db_path))


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
        run_pipeline_main(run_id=run_id)
        _set_run_state(run_id, "completed", "Pipeline completed", 100.0)
    except Exception as exc:
        _set_run_state(run_id, "failed", "Pipeline failed", 0.0, str(exc))


@app.post("/token")
def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), _: None = Depends(require_localhost)):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token = create_access_token(data={"sub": user["username"]})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/health")
def health(_: None = Depends(require_localhost)) -> dict:
    return {"status": "ok"}


@app.post("/upload")
def upload_files(current_user: dict = Depends(get_current_user), files: list[UploadFile] = File(...), _: None = Depends(require_localhost)) -> dict:
    incoming = PROJECT_ROOT / "data" / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
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


@app.post("/run-pipeline")
def run_pipeline_endpoint(current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    _ensure_app_db()
    run_id = str(uuid.uuid4())
    conn = get_connection(str(_db_path()))
    try:
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


@app.get("/status/{run_id}")
def status_endpoint(run_id: str, current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
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
    return {
        "run_id": row[0],
        "status": row[1],
        "progress": row[2],
        "message": row[3],
        "error": row[4],
        "created_at": row[5],
        "updated_at": row[6],
    }


@app.get("/results")
def results_endpoint(current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    _ensure_app_db()
    conn = get_connection(str(_db_path()))
    try:
        conn.row_factory = lambda cursor, row: {col[0]: row[idx] for idx, col in enumerate(cursor.description)}
        rows = conn.execute("SELECT * FROM compliance_matrix ORDER BY spec_id, vendor_id").fetchall()
    finally:
        conn.close()
    return {"results": rows}


@app.get("/parsed-document/{doc_id}")
def parsed_document_endpoint(doc_id: str, current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
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
def pdf_endpoint(file_name: str, current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)):
    pdf_path = _incoming_dir() / Path(file_name).name
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(str(pdf_path), media_type="application/pdf", filename=pdf_path.name)


@app.post("/override")
def override_endpoint(payload: dict, current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    spec_id = str(payload.get("spec_id", "")).strip()
    vendor_id = str(payload.get("vendor_id", "")).strip()
    new_status = str(payload.get("new_status", "")).strip()
    justification = str(payload.get("justification", "")).strip()
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
        citation_excerpt = row[2] if row and len(row) > 2 else ""
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


@app.get("/report")
def report_endpoint(current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)):
    report_path = _report_path()
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(str(report_path), filename=report_path.name)


@app.get("/secure")
def secure_endpoint(current_user: dict = Depends(get_current_user), _: None = Depends(require_localhost)) -> dict:
    return {"status": "ok", "user": current_user["username"]}
