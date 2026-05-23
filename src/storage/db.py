import sqlite3
from pathlib import Path
import os


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
    if column_name in _table_columns(conn, table_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def get_connection(db_path: str) -> sqlite3.Connection:
    """Return a hardened sqlite3 connection with safe PRAGMAs applied.

    The connection enables foreign keys, WAL journaling and reasonable
    timeouts. `check_same_thread` is set to False to allow usage from
    worker threads (adjust if your app is single-threaded).
    """
    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        timeout=30,
        check_same_thread=False,
    )
    # Apply recommended PRAGMAs for integrity and durability
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")
    try:
        cur.execute("PRAGMA journal_mode = WAL;")
    except Exception:
        # Some SQLite builds/platforms may not support WAL; ignore gracefully
        pass
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA secure_delete = ON;")
    cur.close()
    return conn


def init_db(db_path: str) -> None:
    """Initialize database schema from the repository `schema.sql` file.

    Uses the package-local `schema.sql` file to avoid relative-path attacks.
    Ensures destination directory exists and sets restrictive permissions when
    possible.
    """
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # create an empty DB file if it doesn't exist so we can set perms on it
    if not db_file.exists():
        db_file.touch()
        try:
            # POSIX-only: set file to owner read/write only
            os.chmod(db_file, 0o600)
        except Exception:
            # ignore on platforms that don't support chmod semantics
            pass

    # Read schema relative to this module to avoid working-directory tricks
    schema_path = Path(__file__).parent / "schema.sql"
    with get_connection(str(db_file)) as conn:
        with open(schema_path, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        _ensure_column(conn, "compliance_matrix", "citation_doc_id", "citation_doc_id TEXT")
        _ensure_column(conn, "compliance_matrix", "citation_excerpt", "citation_excerpt TEXT")
        _ensure_column(conn, "compliance_matrix", "citation_page", "citation_page INTEGER")
        _ensure_column(conn, "compliance_matrix", "citation_bbox", "citation_bbox TEXT")
