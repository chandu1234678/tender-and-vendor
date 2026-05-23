CREATE TABLE IF NOT EXISTS parsed_documents (
    doc_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    page INTEGER NOT NULL,
    bbox TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compliance_matrix (
    spec_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    status TEXT NOT NULL,
    citation TEXT NOT NULL,
    citation_doc_id TEXT,
    citation_excerpt TEXT,
    reasoning TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY (spec_id, vendor_id)
);

CREATE TABLE IF NOT EXISTS autonomous_feedback_loop (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    original_status TEXT NOT NULL,
    corrected_status TEXT NOT NULL,
    justification TEXT NOT NULL,
    context TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS training_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spec_id TEXT NOT NULL,
    vendor_id TEXT NOT NULL,
    doc_id TEXT,
    page INTEGER,
    bbox TEXT,
    excerpt TEXT,
    label TEXT,
    processed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
