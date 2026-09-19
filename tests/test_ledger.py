import os
import sqlite3
import tempfile
import pytest

from scripts.fsm import State
from scripts.ledger import Ledger


@pytest.fixture
def temp_ledger():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_guard.sqlite")
        ledger = Ledger(db_path=db_path)
        yield ledger


def test_schema_initialization(temp_ledger):
    conn = sqlite3.connect(temp_ledger.db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in c.fetchall()}
    assert "sessions" in tables
    assert "file_modifications" in tables
    assert "failure_events" in tables
    assert "turn_events" in tables
    conn.close()


def test_session_lifecycle_and_state(temp_ledger):
    session = temp_ledger.init_session("sess-1", metadata={"user": "test"})
    assert session["session_id"] == "sess-1"
    assert session["state"] == State.NORMAL.value
    assert session["failure_streak"] == 0

    assert temp_ledger.get_state("sess-1") == State.NORMAL.value
    temp_ledger.set_state("sess-1", State.FAILURE_STAGE_1.value)
    assert temp_ledger.get_state("sess-1") == State.FAILURE_STAGE_1.value


def test_file_modifications_and_verification(temp_ledger):
    temp_ledger.init_session("sess-mod")
    assert not temp_ledger.is_unverified("sess-mod")

    temp_ledger.record_file_edit("sess-mod", "src/core.py")
    assert temp_ledger.is_unverified("sess-mod")
    assert "src/core.py" in temp_ledger.get_unverified_files("sess-mod")

    temp_ledger.record_file_edit("sess-mod", "src/utils.py")
    assert len(temp_ledger.get_unverified_files("sess-mod")) == 2

    # Verification marks all verified
    temp_ledger.mark_files_verified("sess-mod")
    assert not temp_ledger.is_unverified("sess-mod")
    assert len(temp_ledger.get_unverified_files("sess-mod")) == 0


def test_test_results_and_state_transitions(temp_ledger):
    temp_ledger.init_session("sess-fsm")
    temp_ledger.record_file_edit("sess-fsm", "src/app.py")

    # 1st test failure -> FAILURE_STAGE_1
    state, streak = temp_ledger.record_test_result(
        session_id="sess-fsm",
        command="pytest tests/test_app.py",
        exit_code=1,
        output_summary="AssertionError: 1 != 2"
    )
    assert state == State.FAILURE_STAGE_1.value
    assert streak == 1
    assert temp_ledger.get_failure_streak("sess-fsm") == 1
    assert temp_ledger.is_unverified("sess-fsm")

    # 2nd test failure -> FAILURE_STAGE_2_TRIPPED
    state, streak = temp_ledger.record_test_result(
        session_id="sess-fsm",
        command="pytest tests/test_app.py",
        exit_code=1,
        output_summary="AssertionError: 1 != 2"
    )
    assert state == State.FAILURE_STAGE_2_TRIPPED.value
    assert streak == 2

    # Passing test -> RECOVERY_VERIFIED and marks files verified
    state, streak = temp_ledger.record_test_result(
        session_id="sess-fsm",
        command="pytest tests/test_app.py",
        exit_code=0,
        output_summary="1 passed"
    )
    assert state == State.RECOVERY_VERIFIED.value
    assert streak == 0
    assert not temp_ledger.is_unverified("sess-fsm")


def test_reset_failures(temp_ledger):
    temp_ledger.init_session("sess-reset")
    temp_ledger.record_test_result("sess-reset", "pytest", 1)
    temp_ledger.record_test_result("sess-reset", "pytest", 1)
    assert temp_ledger.get_state("sess-reset") == State.FAILURE_STAGE_2_TRIPPED.value

    temp_ledger.reset_failures("sess-reset")
    assert temp_ledger.get_state("sess-reset") == State.NORMAL.value
    assert temp_ledger.get_failure_streak("sess-reset") == 0


def test_turn_increment_and_events(temp_ledger):
    temp_ledger.init_session("sess-turn")
    assert temp_ledger.increment_turn("sess-turn") == 1
    assert temp_ledger.increment_turn("sess-turn") == 2
    temp_ledger.record_tool_call("sess-turn", "bash", {"command": "ls"})
    temp_ledger.record_turn_event("sess-turn", 2, "CHECKPOINT", "done")
