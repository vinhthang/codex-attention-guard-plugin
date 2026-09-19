import json
import os
import sqlite3
import tempfile
import pytest

from scripts.telemetry_audit import analyze_db, format_comparison_table, format_report


@pytest.fixture
def sample_audit_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_thread_history.sqlite")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE thread_items (
                thread_id TEXT,
                turn_id TEXT,
                item_id TEXT PRIMARY KEY,
                rollout_ordinal INTEGER,
                created_at_ms INTEGER,
                item_json TEXT,
                item_type TEXT,
                updated_at_ordinal INTEGER
            );
        """)

        # Sample data:
        # Thread 1: 2 turns
        # Item 1: commandExecution, exitCode=0, output len=100
        cmd1 = json.dumps({"command": "ls", "exitCode": 0, "aggregatedOutput": "a" * 100})
        # Item 2: commandExecution, exitCode=1, output len=3000 (>2KB)
        cmd2 = json.dumps({"command": "pytest", "exitCode": 1, "aggregatedOutput": "e" * 3000})
        # Item 3: fileChange immediately after failure (speculative edit!)
        fc1 = json.dumps({"changes": [{"path": "src/app.py"}]})
        # Item 4: commandExecution, exitCode=1, output len=200 (streak=2)
        cmd3 = json.dumps({"command": "pytest", "exitCode": 1, "aggregatedOutput": "e" * 200})
        # Item 5: commandExecution, exitCode=1, output len=200 (streak=3)
        cmd4 = json.dumps({"command": "pytest", "exitCode": 1, "aggregatedOutput": "e" * 200})
        # Item 6: contextCompaction
        cc1 = json.dumps({})
        # Item 7: commandExecution, exitCode=0, output len=500 (recovers)
        cmd5 = json.dumps({"command": "pytest", "exitCode": 0, "aggregatedOutput": "p" * 500})

        items = [
            ("t1", "turn1", "i1", 1, 1000, cmd1, "commandExecution", 1),
            ("t1", "turn1", "i2", 2, 2000, cmd2, "commandExecution", 2),
            ("t1", "turn1", "i3", 3, 2500, fc1, "fileChange", 3),
            ("t1", "turn2", "i4", 4, 3000, cmd3, "commandExecution", 4),
            ("t1", "turn2", "i5", 5, 4000, cmd4, "commandExecution", 5),
            ("t1", "turn2", "i6", 6, 4500, cc1, "contextCompaction", 6),
            ("t1", "turn2", "i7", 7, 5000, cmd5, "commandExecution", 7),
        ]

        conn.executemany("""
            INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, items)
        conn.commit()
        conn.close()

        yield db_path


def test_analyze_db_metrics(sample_audit_db):
    stats = analyze_db(sample_audit_db)

    assert stats["threads"] == 1
    assert stats["turns"] == 2
    assert stats["commands"] == 5
    assert stats["oversized_2kb"] == 1
    assert stats["max_spike"] == 3000
    assert stats["total_chars"] == 100 + 3000 + 200 + 200 + 500
    assert stats["avg_chars"] == (100 + 3000 + 200 + 200 + 500) / 5
    assert stats["compactions"] == 1
    assert stats["failed_commands"] == 3
    # Consecutive failures: i2, i4, i5 is a streak of 3 failed commands
    assert stats["multi_failure_streaks"] == 1
    assert stats["max_streak"] == 3
    # Speculative edit: i3 follows failed i2
    assert stats["speculative_edits"] == 1


def test_analyze_db_time_filtering(sample_audit_db):
    # Before timestamp 3000
    before = analyze_db(sample_audit_db, end_ts=3000)
    assert before["commands"] == 2
    assert before["oversized_2kb"] == 1

    # Since timestamp 3000
    after = analyze_db(sample_audit_db, start_ts=3000)
    assert after["commands"] == 3
    assert after["oversized_2kb"] == 0
    assert after["compactions"] == 1


def test_format_reports(sample_audit_db):
    before = analyze_db(sample_audit_db, end_ts=3000)
    after = analyze_db(sample_audit_db, start_ts=3000)

    report = format_report(before)
    assert "Attention Guard Telemetry" in report
    assert "Commands Executed**: 2" in report

    table = format_comparison_table(before, after, "2026-09-20")
    assert "| Telemetry Metric | Before Baseline | After Installation | Delta / Impact |" in table
    assert "Max Single Output Spike" in table
