import json
import sqlite3
from pathlib import Path

from src.app.run_pipeline import _citation_doc_id, _load_blocks_from_db


def test_load_blocks_from_db_preserves_doc_id(tmp_path):
    db_path = tmp_path / "app.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE parsed_documents (doc_id TEXT PRIMARY KEY, file_name TEXT NOT NULL, page INTEGER NOT NULL, bbox TEXT NOT NULL, text TEXT NOT NULL)"
    )
    cur.execute(
        "INSERT INTO parsed_documents (doc_id, file_name, page, bbox, text) VALUES (?, ?, ?, ?, ?)",
        ("vendor1:1:3", "vendor1.pdf", 1, json.dumps([0, 0, 100, 100]), "Sample text"),
    )
    conn.commit()

    blocks = _load_blocks_from_db(cur, "vendor1.pdf")
    assert len(blocks) == 1
    assert blocks[0]["doc_id"] == "vendor1:1:3"
    assert blocks[0]["page"] == 1
    assert blocks[0]["bbox"] == [0, 0, 100, 100]
    assert blocks[0]["text"] == "Sample text"

    citation_id = _citation_doc_id("vendor1", blocks)
    assert citation_id == "vendor1:1:3"


def test_citation_doc_id_falls_back_when_doc_id_missing():
    blocks = [{"page": 2, "bbox": [10, 10, 50, 50], "text": "Some text"}]
    citation_id = _citation_doc_id("vendor2", blocks)
    assert citation_id == "vendor2:2:0"
