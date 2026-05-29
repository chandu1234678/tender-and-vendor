import sqlite3

from src import evaluator


def test_batch_hit_counts(tmp_path):
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE heuristic_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_type TEXT,
        pattern TEXT,
        verdict TEXT,
        weight REAL,
        hit_count INTEGER DEFAULT 0
    )
    """)
    cur.execute(
        "INSERT INTO heuristic_rules (rule_type, pattern, verdict, weight, hit_count) VALUES (?, ?, ?, ?, ?)",
        ("keyword", "p1", "YES", 1.0, 0),
    )
    conn.commit()
    conn.close()

    # Ensure buffer is clean, then call _increment_hit multiple times (in-memory)
    evaluator._hit_counts.clear()
    for _ in range(7):
        evaluator._increment_hit("p1", db_path=str(db))

    # Nothing yet in DB until flush
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute("SELECT hit_count FROM heuristic_rules WHERE pattern=?", ("p1",))
    assert cur.fetchone()[0] == 0
    conn.close()

    # Internal buffer should hold the aggregated counts
    assert evaluator._hit_counts.get("p1") == 7

    # Flush and verify aggregated count applied
    updated = evaluator.flush_hit_counts(db_path=str(db))
    assert updated >= 1

    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute("SELECT hit_count FROM heuristic_rules WHERE pattern=?", ("p1",))
    assert cur.fetchone()[0] == 7
    conn.close()
