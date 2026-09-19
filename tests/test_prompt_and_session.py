import json
import os
import subprocess
import sys
import tempfile
import pytest

from scripts.fsm import State
from scripts.ledger import Ledger


@pytest.fixture
def test_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_guard.sqlite")
        env = os.environ.copy()
        env["ATTENTION_GUARD_DB"] = db_path
        env["CODEX_SESSION_ID"] = "test-session"
        yield db_path, env


def test_session_init_execution(test_env):
    db_path, env = test_env
    script = os.path.join(os.path.dirname(__file__), "..", "scripts", "session_init.py")
    res = subprocess.run(
        [sys.executable, script],
        input=json.dumps({"session_id": "test-session", "cwd": "/tmp"}),
        text=True,
        capture_output=True,
        env=env
    )
    assert res.returncode == 0
    ledger = Ledger(db_path)
    session = ledger.get_session("test-session")
    assert session is not None
    assert session["session_id"] == "test-session"
    assert session["state"] == State.NORMAL.value


def test_prompt_refresh_execution(test_env):
    db_path, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-session")

    script = os.path.join(os.path.dirname(__file__), "..", "scripts", "prompt_refresh.py")

    # Turns 1-4 in NORMAL state: passthrough
    for i in range(1, 5):
        res = subprocess.run(
            [sys.executable, script],
            input=json.dumps({"session_id": "test-session"}),
            text=True,
            capture_output=True,
            env=env
        )
        assert res.returncode == 0
        out = json.loads(res.stdout)
        assert "system_reminder" not in out

    # Turn 5: triggers reminder injection
    res = subprocess.run(
        [sys.executable, script],
        input=json.dumps({"session_id": "test-session"}),
        text=True,
        capture_output=True,
        env=env
    )
    assert res.returncode == 0
    out = json.loads(res.stdout)
    assert "system_reminder" in out
    assert "ATTENTION GUARD REMINDER" in out["system_reminder"]
    assert out["turn_count"] == 5

    # Trigger failure state: even on turn 6 it should inject reminder
    ledger.set_state("test-session", State.FAILURE_STAGE_1.value)
    res = subprocess.run(
        [sys.executable, script],
        input=json.dumps({"session_id": "test-session"}),
        text=True,
        capture_output=True,
        env=env
    )
    assert res.returncode == 0
    out = json.loads(res.stdout)
    assert "system_reminder" in out
    assert "FAILURE_STAGE_1" in out["system_reminder"]
