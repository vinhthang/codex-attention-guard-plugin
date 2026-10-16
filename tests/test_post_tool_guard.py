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
        codex_home = os.path.join(tmpdir, "codex_home")
        os.makedirs(codex_home, exist_ok=True)
        env = os.environ.copy()
        env["ATTENTION_GUARD_DB"] = db_path
        env["CODEX_HOME"] = codex_home
        env["CODEX_SESSION_ID"] = "test-post-session"
        yield db_path, codex_home, env


def run_post_guard(payload, env):
    script = os.path.join(os.path.dirname(__file__), "..", "scripts", "post_tool_guard.py")
    res = subprocess.run(
        [sys.executable, script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env
    )
    return res


def test_file_mutation_tracking(test_env):
    db_path, _, env = test_env
    ledger = Ledger(db_path)

    payload = {
        "tool_name": "edit_file",
        "tool_input": {"path": "src/module_a.py", "content": "print('hello')"},
        "tool_result": {"status": 0}
    }
    res = run_post_guard(payload, env)
    assert res.returncode == 0
    assert ledger.is_unverified("test-post-session")
    assert "src/module_a.py" in ledger.get_unverified_files("test-post-session")


def test_failure_increment_and_state_transitions(test_env):
    db_path, _, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-post-session")

    # 1st test failure
    payload1 = {
        "tool_name": "bash",
        "tool_input": {"command": "pytest -v"},
        "tool_result": {"exit_code": 1, "output": "FAILED test_a.py::test_foo"}
    }
    res1 = run_post_guard(payload1, env)
    assert res1.returncode == 0
    assert ledger.get_state("test-post-session") == State.FAILURE_STAGE_1.value
    assert ledger.get_failure_streak("test-post-session") == 1
    assert "[ATTENTION GUARD - ATTEMPT 1]: Test failure detected. Speculative in-place edits are discouraged. Author an isolated test reproducer (test_*, *_test.*) or diagnostic doc (diagnosis.md, rca.md) before fixing code.\n" in res1.stderr

    # 2nd consecutive test failure -> TRIPPED
    payload2 = {
        "tool_name": "bash",
        "tool_input": {"command": "cargo test"},
        "tool_result": {"exit_code": 101, "output": "error: test failed"}
    }
    res2 = run_post_guard(payload2, env)
    assert res2.returncode == 0
    assert ledger.get_state("test-post-session") == State.FAILURE_STAGE_2_TRIPPED.value
    assert ledger.get_failure_streak("test-post-session") == 2
    assert "[ATTENTION GUARD - ATTEMPT 2]: Consecutive test failures. Circuit breaker tripped: stop speculative trial-and-error edits immediately. Isolate root cause in diagnosis.md or rca.md.\n" in res2.stderr


def test_output_passes_through_untouched_without_truncation(test_env):
    db_path, codex_home, env = test_env
    large_output = "ERROR TRACE LINE\n" * 200  # ~3,400 chars (>2KB)
    assert len(large_output) > 2000

    payload = {
        "tool_name": "bash",
        "tool_input": {"command": "pytest"},
        "tool_result": {"exit_code": 1, "output": large_output}
    }
    res = run_post_guard(payload, env)
    assert res.returncode == 0

    # Verify output payload remains completely untouched without arbitrary truncation
    out = json.loads(res.stdout)
    res_output = out["tool_result"]["output"]
    assert res_output == large_output
    assert len(res_output) == len(large_output)


def test_test_success_resets_failures_and_verifies_files(test_env):
    db_path, _, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-post-session")
    ledger.record_file_edit("test-post-session", "src/auth.py")
    ledger.record_test_result("test-post-session", "pytest", 1)
    assert ledger.is_unverified("test-post-session")
    assert ledger.get_state("test-post-session") == State.FAILURE_STAGE_1.value

    # Passing test command
    payload = {
        "tool_name": "bash",
        "tool_input": {"command": "pytest -v"},
        "tool_result": {"exit_code": 0, "output": "3 passed in 0.12s"}
    }
    res = run_post_guard(payload, env)
    assert res.returncode == 0
    assert ledger.get_state("test-post-session") == State.RECOVERY_VERIFIED.value
    assert ledger.get_failure_streak("test-post-session") == 0
    assert not ledger.is_unverified("test-post-session")
