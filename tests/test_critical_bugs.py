import sqlite3
import inspect
from pathlib import Path

import pytest

from src.engine import orchestrator
from src import evaluator
from src.engine import ollama_client


def test_trim_context_default_is_large_enough():
    # Expectation: default max_chars should be at least 3500
    defaults = orchestrator._trim_context.__defaults__
    assert defaults and defaults[0] >= 3500


def test_increment_hit_uses_single_connection(monkeypatch):
    # Calling _increment_hit many times should reuse a single connection (batching)
    calls = {"count": 0}

    def fake_connect(path, timeout=5, check_same_thread=False):
        calls["count"] += 1
        class DummyConn:
            def execute(self, *a, **k):
                return None

            def commit(self):
                return None

            def close(self):
                return None

        return DummyConn()

    monkeypatch.setattr(evaluator, "sqlite3", type("S", (), {"connect": fake_connect}))

    for _ in range(10):
        evaluator._increment_hit("test-pattern", db_path=":memory:")

    # Expectation: batching would result in 1 connection; assert that here.
    # With batching enabled we expect zero immediate DB connects
    assert calls["count"] == 0


def test_vendorindex_is_immutable():
    blocks = [{"text": "A block"}]
    idx = orchestrator.VendorIndex.build(blocks)
    # Expectation: dataclass frozen=True should prevent mutation of list fields
    with pytest.raises(Exception):
        idx.blocks.append({"text": "another"})


def test_generate_lmstudio_uses_openai_compatible_endpoint_and_max_tokens(monkeypatch):
    captured = {}

    def fake_http_json(method, url, payload=None):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        return {}

    monkeypatch.setattr(ollama_client, "_http_json", fake_http_json)

    ollama_client._generate_lmstudio("model-x", "prompt", 0.1, 80)

    # Expectation: use OpenAI-compatible /v1/chat/completions and include max_tokens in payload
    assert "/v1/chat/completions" in captured.get("url", "")
    assert isinstance(captured.get("payload"), dict)
    assert "max_tokens" in (captured.get("payload") or {})


def test_retrain_from_feedback_inserts_bigrams_not_single_tokens(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    # Create minimal tables
    cur.execute("""
    CREATE TABLE training_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        spec_id TEXT,
        vendor_id TEXT,
        excerpt TEXT,
        label TEXT,
        processed INTEGER DEFAULT 0
    )
    """)
    cur.execute("""
    CREATE TABLE heuristic_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_type TEXT,
        pattern TEXT,
        verdict TEXT,
        weight REAL,
        source TEXT DEFAULT 'system'
    )
    """)
    # Insert one training example
    cur.execute(
        "INSERT INTO training_queue (spec_id, vendor_id, excerpt, label) VALUES (?, ?, ?, ?)",
        ("S1", "V1", "The processor meets the 8-core requirement", "YES"),
    )
    conn.commit()
    conn.close()

    added = evaluator.retrain_from_feedback(db_path=str(db_path))

    # Expectation: retrain should add bigram patterns (contain a space), not single tokens
    conn = sqlite3.connect(str(db_path))
    rows = [r[0] for r in conn.execute("SELECT pattern FROM heuristic_rules").fetchall()]
    conn.close()

    assert added > 0
    assert all(" " in p for p in rows), f"Expected bigrams, got: {rows}"
