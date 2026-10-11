import json
import os
import subprocess
import sys
import tempfile
import pytest

from scripts.fsm import State
from scripts.ledger import Ledger
from scripts.pre_tool_guard import wrap_command_if_needed


def test_command_wrapping_logic():
    # Test runners -> rtk test
    cmd, mod = wrap_command_if_needed("pytest -v")
    assert mod and cmd == "rtk test pytest -v"

    cmd, mod = wrap_command_if_needed("python3 -m pytest tests/")
    assert mod and cmd == "rtk test python3 -m pytest tests/"

    cmd, mod = wrap_command_if_needed("cargo test")
    assert mod and cmd == "rtk test cargo test"

    cmd, mod = wrap_command_if_needed("npm test")
    assert mod and cmd == "rtk test npm test"

    cmd, mod = wrap_command_if_needed("vitest run")
    assert mod and cmd == "rtk test vitest run"

    cmd, mod = wrap_command_if_needed("go test ./...")
    assert mod and cmd == "rtk test go test ./..."

    cmd, mod = wrap_command_if_needed("dotnet test")
    assert mod and cmd == "rtk test dotnet test"

    # Build runners -> rtk err
    cmd, mod = wrap_command_if_needed("cargo build --release")
    assert mod and cmd == "rtk err cargo build --release"

    cmd, mod = wrap_command_if_needed("mvn clean compile")
    assert mod and cmd == "rtk err mvn clean compile"

    # Already prefixed -> no change
    cmd, mod = wrap_command_if_needed("rtk pytest -v")
    assert not mod and cmd == "rtk pytest -v"

    cmd, mod = wrap_command_if_needed("rtk test cargo test")
    assert not mod and cmd == "rtk test cargo test"

    # Unrelated command -> no change
    cmd, mod = wrap_command_if_needed("git status")
    assert not mod and cmd == "git status"


@pytest.fixture
def test_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_guard.sqlite")
        env = os.environ.copy()
        env["ATTENTION_GUARD_DB"] = db_path
        env["CODEX_SESSION_ID"] = "test-session"
        yield db_path, env


def run_pre_guard(payload, env):
    script = os.path.join(os.path.dirname(__file__), "..", "scripts", "pre_tool_guard.py")
    res = subprocess.run(
        [sys.executable, script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env
    )
    return res


def test_normal_state_allows_production_mutations(test_env):
    db_path, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-session")

    payload = {
        "tool_name": "edit_file",
        "tool_input": {"path": "src/user_service.py", "content": "print('ok')"}
    }
    res = run_pre_guard(payload, env)
    assert res.returncode == 0


def test_failure_stage_1_blocks_production_allows_reproducer(test_env):
    db_path, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-session")
    ledger.set_state("test-session", State.FAILURE_STAGE_1.value)

    # 1. Edit to production file must be blocked
    prod_payload = {
        "tool_name": "edit_file",
        "tool_input": {"path": "src/user_service.py", "content": "print('fix')"}
    }
    res = run_pre_guard(prod_payload, env)
    assert res.returncode == 1
    assert "Speculative edit blocked" in res.stderr

    # 2. Edit to test reproducer file must be permitted
    test_payload = {
        "tool_name": "write_file",
        "tool_input": {"path": "tests/test_user_service.py", "content": "def test_fail(): pass"}
    }
    res = run_pre_guard(test_payload, env)
    assert res.returncode == 0

    # 3. Edit to diagnostic file must be permitted
    diag_payload = {
        "tool_name": "write_file",
        "tool_input": {"path": "diagnosis.md", "content": "# Root Cause"}
    }
    res = run_pre_guard(diag_payload, env)
    assert res.returncode == 0


def test_failure_stage_2_blocks_all_mutations(test_env):
    db_path, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-session")
    ledger.set_state("test-session", State.FAILURE_STAGE_2_TRIPPED.value)

    # Even test files are blocked in Stage 2
    test_payload = {
        "tool_name": "write_file",
        "tool_input": {"path": "tests/test_fix.py", "content": "def test_x(): pass"}
    }
    res = run_pre_guard(test_payload, env)
    assert res.returncode == 1
    assert "Circuit breaker TRIPPED" in res.stderr


def test_failure_stage_2_allows_diagnostic_and_markdown(test_env):
    db_path, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-session")
    ledger.set_state("test-session", State.FAILURE_STAGE_2_TRIPPED.value)

    for p in ["diagnosis.md", "docs/walkthrough.md", "rca.md"]:
        res = run_pre_guard({"tool_name": "write_file", "tool_input": {"path": p, "content": "diag content"}}, env)
        assert res.returncode == 0

    res = run_pre_guard({"tool_name": "write_file", "tool_input": {"path": "src/service.py", "content": "print('ok')"}}, env)
    assert res.returncode == 1
    assert "Circuit breaker TRIPPED" in res.stderr


def test_failure_stage_1_allows_markdown_docs(test_env):
    db_path, env = test_env
    ledger = Ledger(db_path)
    ledger.init_session("test-session")
    ledger.set_state("test-session", State.FAILURE_STAGE_1.value)

    for p in ["README.md", "docs/spec.md"]:
        res = run_pre_guard({"tool_name": "write_file", "tool_input": {"path": p, "content": "# Doc"}}, env)
        assert res.returncode == 0


def test_pre_guard_command_wrapping_execution(test_env):
    _, env = test_env
    payload = {
        "tool_name": "bash",
        "tool_input": {"command": "pytest -q"}
    }
    res = run_pre_guard(payload, env)
    assert res.returncode == 0
    out = json.loads(res.stdout)
    assert out["tool_input"]["command"] == "rtk test pytest -q"
