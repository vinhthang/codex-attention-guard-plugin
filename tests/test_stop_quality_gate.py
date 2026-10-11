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
        workspace_dir = os.path.join(tmpdir, "workspace")
        os.makedirs(workspace_dir, exist_ok=True)
        env = os.environ.copy()
        env["ATTENTION_GUARD_DB"] = db_path
        env["CODEX_SESSION_ID"] = "test-stop-session"
        yield db_path, workspace_dir, env


def run_stop_gate(payload, env, cwd=None):
    script = os.path.join(os.path.dirname(__file__), "..", "scripts", "stop_quality_gate.py")
    res = subprocess.run(
        [sys.executable, script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        cwd=cwd
    )
    return res


def test_rejection_on_unverified_edits(test_env):
    db_path, workspace_dir, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-stop-session")
    ledger.record_file_edit("test-stop-session", "src/service.py")
    assert ledger.is_unverified("test-stop-session")

    # Walkthrough present, but edits unverified -> REJECTED
    with open(os.path.join(workspace_dir, "walkthrough.md"), "w") as f:
        f.write("# Walkthrough")

    payload = {"cwd": workspace_dir}
    res = run_stop_gate(payload, env, cwd=workspace_dir)
    assert res.returncode == 1
    assert "Unverified modifications remain" in res.stderr


def test_rejection_on_missing_walkthrough(test_env):
    db_path, workspace_dir, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-stop-session")
    ledger.record_file_edit("test-stop-session", "src/service.py")
    ledger.mark_files_verified("test-stop-session")
    assert not ledger.is_unverified("test-stop-session")

    # No walkthrough file in workspace -> REJECTED
    payload = {"cwd": workspace_dir}
    res = run_stop_gate(payload, env, cwd=workspace_dir)
    assert res.returncode == 1
    assert "Missing walkthrough or summary artifact" in res.stderr


def test_pass_on_verified_edits_and_walkthrough(test_env):
    db_path, workspace_dir, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-stop-session")
    ledger.record_file_edit("test-stop-session", "src/service.py")
    ledger.mark_files_verified("test-stop-session")
    assert not ledger.is_unverified("test-stop-session")

    # Author walkthrough.md
    walkthrough_path = os.path.join(workspace_dir, "walkthrough.md")
    with open(walkthrough_path, "w", encoding="utf-8") as f:
        f.write("# Turn Walkthrough\nVerified all tests pass.\n")

    payload = {"cwd": workspace_dir}
    res = run_stop_gate(payload, env, cwd=workspace_dir)
    assert res.returncode == 0


def test_pass_on_markdown_only_edits_without_tests(test_env):
    db_path, workspace_dir, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-stop-session")
    ledger.record_file_edit("test-stop-session", "README.md")

    walkthrough_path = os.path.join(workspace_dir, "walkthrough.md")
    with open(walkthrough_path, "w", encoding="utf-8") as f:
        f.write("# Walkthrough\nDocs updated.\n")

    payload = {"cwd": workspace_dir}
    res = run_stop_gate(payload, env, cwd=workspace_dir)
    assert res.returncode == 0


def test_pass_on_no_modifications_without_walkthrough(test_env):
    db_path, workspace_dir, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-stop-session")

    payload = {"cwd": workspace_dir}
    res = run_stop_gate(payload, env, cwd=workspace_dir)
    assert res.returncode == 0


def test_pass_when_circuit_breaker_tripped(test_env):
    db_path, workspace_dir, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-stop-session")
    ledger.set_state("test-stop-session", State.FAILURE_STAGE_2_TRIPPED.value)
    ledger.record_file_edit("test-stop-session", "src/service.py")

    payload = {"cwd": workspace_dir}
    res = run_stop_gate(payload, env, cwd=workspace_dir)
    assert res.returncode == 0
    assert "[STOP GATE] Circuit breaker is TRIPPED" in res.stderr


def test_pass_on_bypass_flag(test_env):
    db_path, workspace_dir, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-stop-session")
    ledger.record_file_edit("test-stop-session", "src/service.py")

    payload = {"cwd": workspace_dir, "bypass": True}
    res = run_stop_gate(payload, env, cwd=workspace_dir)
    assert res.returncode == 0
