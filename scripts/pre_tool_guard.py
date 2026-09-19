import json
import os
import re
import shlex
import sys
from typing import Any, Dict, Optional, Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from fsm import State, can_mutate_file
from ledger import Ledger

FILE_MUTATION_TOOLS = {
    "edit_file",
    "write_file",
    "replace_file_content",
    "create_file",
    "file_edit",
    "apply_diff",
    "write_to_file",
    "edit",
}

COMMAND_TOOLS = {
    "bash",
    "execute_command",
    "run_command",
    "shell",
    "terminal",
}

TEST_PATTERNS = [
    r"\bpytest\b",
    r"\bpython3?\s+-m\s+pytest\b",
    r"\bcargo\s+test\b",
    r"\bmvn\s+.*test\b",
    r"\bnpm\s+(?:run\s+)?test\b",
    r"\bpnpm\s+(?:run\s+)?test\b",
    r"\byarn\s+(?:run\s+)?test\b",
    r"\bvitest\b",
    r"\bnpx\s+vitest\b",
    r"\bgo\s+test\b",
    r"\bdotnet\s+test\b",
    r"\bmake\s+test\b",
    r"\b\./gradlew\s+test\b",
]

BUILD_PATTERNS = [
    r"\bcargo\s+build\b",
    r"\bmvn\s+(?:clean\s+)?(?:compile|package|install|verify)\b",
    r"\bmvn\b",
    r"\bgo\s+build\b",
    r"\bdotnet\s+build\b",
    r"\bmake\b",
    r"\b\./gradlew\s+build\b",
    r"\bnpm\s+run\s+build\b",
    r"\bpnpm\s+run\s+build\b",
    r"\byarn\s+build\b",
]


def extract_file_path(tool_input: Any) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("path", "file_path", "TargetFile", "target_file", "file", "filename", "filePath"):
        val = tool_input.get(key)
        if val:
            return str(val)
    return ""


def wrap_command_if_needed(cmd: str) -> Tuple[str, bool]:
    stripped = cmd.strip()
    if not stripped:
        return cmd, False

    # If already prefixed with rtk
    if stripped.startswith("rtk ") or stripped == "rtk":
        return cmd, False

    # Check test runners
    for pat in TEST_PATTERNS:
        if re.search(pat, stripped):
            return f"rtk test {stripped}", True

    # Check build runners
    for pat in BUILD_PATTERNS:
        if re.search(pat, stripped):
            return f"rtk err {stripped}", True

    return cmd, False


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
    state = ledger.get_state(session_id)

    tool_name = (
        data.get("tool_name")
        or data.get("name")
        or data.get("tool")
        or ""
    ).lower()

    tool_input = data.get("tool_input")
    if tool_input is None:
        tool_input = data.get("parameters") or data.get("arguments") or data.get("args") or data

    # 1. Check for file mutations
    target_file = extract_file_path(tool_input)
    is_mutation = (tool_name in FILE_MUTATION_TOOLS) or bool(
        target_file and (tool_input.get("code") or tool_input.get("content") or tool_input.get("patch") or tool_input.get("ReplacementContent"))
    )

    if is_mutation and target_file:
        allowed, err_msg = can_mutate_file(state, target_file)
        if not allowed:
            sys.stderr.write(f"[ATTENTION GUARD REJECTED] {err_msg}\n")
            sys.exit(1)

    # 2. Check for bash / shell commands
    is_command = (tool_name in COMMAND_TOOLS) or ("command" in tool_input if isinstance(tool_input, dict) else False)
    command_str = None
    cmd_key = None

    if isinstance(tool_input, dict):
        for k in ("command", "cmd", "CommandLine"):
            if k in tool_input and isinstance(tool_input[k], str):
                command_str = tool_input[k]
                cmd_key = k
                break
    elif isinstance(data.get("command"), str):
        command_str = data["command"]
        cmd_key = "command"

    if command_str and (is_command or tool_name == ""):
        wrapped_cmd, modified = wrap_command_if_needed(command_str)
        if modified:
            if isinstance(tool_input, dict) and cmd_key:
                tool_input[cmd_key] = wrapped_cmd
            if "command" in data:
                data["command"] = wrapped_cmd
            if "tool_input" in data and isinstance(data["tool_input"], dict):
                data["tool_input"][cmd_key or "command"] = wrapped_cmd

    # Record tool call in ledger
    ledger.record_tool_call(session_id, tool_name, tool_input)

    # Output payload on stdout
    print(json.dumps(data))
    sys.exit(0)


if __name__ == "__main__":
    main()
