import json
import os
import re
import sys
from typing import Any, Dict, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from fsm import State
from ledger import Ledger, _push_metric_async
from pre_tool_guard import BUILD_PATTERNS, FILE_MUTATION_TOOLS, TEST_PATTERNS, extract_file_path


def is_test_or_build_command(cmd: str) -> bool:
    if not cmd:
        return False
    stripped = cmd.strip()
    for pat in TEST_PATTERNS + BUILD_PATTERNS:
        if re.search(pat, stripped):
            return True
    return False


def is_test_command(cmd: str) -> bool:
    if not cmd:
        return False
    stripped = cmd.strip()
    for pat in TEST_PATTERNS:
        if re.search(pat, stripped):
            return True
    return False


def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    session_id = (
        data.get("session_id")
        or data.get("conversation_id")
        or data.get("thread_id")
        or os.environ.get("CODEX_SESSION_ID")
        or "default_session"
    )

    ledger = Ledger()

    tool_name = (
        data.get("tool_name")
        or data.get("name")
        or data.get("tool")
        or ""
    ).lower()

    tool_input = data.get("tool_input")
    if tool_input is None:
        tool_input = data.get("parameters") or data.get("arguments") or data.get("args") or data

    tool_result = data.get("tool_result")
    if tool_result is None:
        tool_result = data.get("result") or {}

    # Extract exit_code
    exit_code = 0
    if isinstance(tool_result, dict):
        if "exit_code" in tool_result:
            exit_code = tool_result["exit_code"]
        elif "exitCode" in tool_result:
            exit_code = tool_result["exitCode"]
        elif "status" in tool_result and isinstance(tool_result["status"], int):
            exit_code = tool_result["status"]
    elif "exit_code" in data:
        exit_code = data["exit_code"]
    elif "exitCode" in data:
        exit_code = data["exitCode"]

    # Extract output
    output_str = ""
    if isinstance(tool_result, dict):
        output_str = str(tool_result.get("output") or tool_result.get("stdout") or tool_result.get("content") or "")
        if not output_str and tool_result.get("stderr"):
            output_str = str(tool_result.get("stderr"))
    elif isinstance(tool_result, str):
        output_str = tool_result
    elif "output" in data:
        output_str = str(data["output"])

    # 1. Track modified files when edit_file / write_file succeeds
    target_file = extract_file_path(tool_input)
    is_mutation = (tool_name in FILE_MUTATION_TOOLS) or bool(
        target_file and (isinstance(tool_input, dict) and (tool_input.get("code") or tool_input.get("content") or tool_input.get("patch") or tool_input.get("ReplacementContent")))
    )

    if is_mutation and target_file and exit_code == 0:
        ledger.record_file_edit(session_id, target_file)

    # 2. Check command executions
    command_str = None
    if isinstance(tool_input, dict):
        for k in ("command", "cmd", "CommandLine"):
            if k in tool_input and isinstance(tool_input[k], str):
                command_str = tool_input[k]
                break
    elif isinstance(data.get("command"), str):
        command_str = data["command"]

    if command_str and is_test_or_build_command(command_str):
        raw_tokens = max(0, len(output_str) // 4)
        filtered_tokens = raw_tokens
        if exit_code != 0:
            new_state, streak = ledger.record_test_result(
                session_id=session_id,
                command=command_str,
                exit_code=exit_code,
                output_summary=output_str,
                log_path=None,
                raw_tokens=raw_tokens,
                filtered_tokens=filtered_tokens,
            )

            if streak == 1:
                sys.stderr.write(
                    "[ATTENTION GUARD - ATTEMPT 1]: Test failure detected. Speculative in-place edits are discouraged. Author an isolated test reproducer (test_*, *_test.*) or diagnostic doc (diagnosis.md, rca.md) before fixing code.\n"
                )
            else:
                sys.stderr.write(
                    f"[ATTENTION GUARD - ATTEMPT {streak}]: Consecutive test failures. Circuit breaker tripped: stop speculative trial-and-error edits immediately. Isolate root cause in diagnosis.md or rca.md.\n"
                )
        else:
            # Command passed
            if is_test_command(command_str):
                new_state, _ = ledger.record_test_result(
                    session_id=session_id,
                    command=command_str,
                    exit_code=0,
                    output_summary=output_str[:200],
                    raw_tokens=raw_tokens,
                    filtered_tokens=filtered_tokens,
                )

    print(json.dumps(data))
    sys.exit(0)


if __name__ == "__main__":
    main()
