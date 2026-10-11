import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

try:
    from .fsm import State
except ImportError:
    from fsm import State
from ledger import Ledger


def is_code_file(path: str) -> bool:
    if not path:
        return False
    lower = path.lower()
    doc_exts = (".md", ".markdown", ".txt", ".rst", ".adoc", ".log")
    if lower.endswith(doc_exts):
        return False
    data_exts = (".json", ".yaml", ".yml", ".toml", ".csv", ".tsv", ".ini", ".cfg", ".xml")
    if lower.endswith(data_exts):
        return False
    return True


def has_walkthrough_artifact(session_id: str, data: dict, ledger: Ledger) -> bool:
    # 1. Check data payload directly
    if data.get("walkthrough") or data.get("walkthrough_path") or data.get("summary") or data.get("artifact_path"):
        return True

    # 2. Check if a walkthrough / summary file was modified in this session
    modified_files = ledger.get_modified_files(session_id)
    for path in modified_files:
        basename = os.path.basename(path).lower()
        if "walkthrough" in basename or basename in ("summary.md", "review.md"):
            return True

    # 3. Check CWD and standard subdirs
    cwd = data.get("cwd") or os.getcwd()
    candidates = [
        "walkthrough.md",
        "WALKTHROUGH.md",
        "summary.md",
        "SUMMARY.md",
        os.path.join("docs", "walkthrough.md"),
        os.path.join("docs", "WALKTHROUGH.md"),
        os.path.join(".codex", "walkthrough.md"),
    ]
    for c in candidates:
        full_p = os.path.join(cwd, c) if not os.path.isabs(c) else c
        if os.path.exists(full_p):
            return True

    # 4. Check CODEX_HOME artifacts
    codex_home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    artifact_path = os.path.join(codex_home, "artifacts", session_id, "walkthrough.md")
    if os.path.exists(artifact_path):
        return True

    # 5. Check brain artifacts directory
    brain_dir = os.path.expanduser("~/.gemini/antigravity/brain")
    brain_artifact = os.path.join(brain_dir, session_id, "walkthrough.md")
    if os.path.exists(brain_artifact):
        return True

    return False


def main() -> None:
    if os.environ.get("ATTENTION_GUARD_BYPASS") == "1":
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    if data.get("bypass") or data.get("force") or data.get("type") in ("question", "escalation", "ask_question", "error"):
        sys.exit(0)

    session_id = (
        data.get("session_id")
        or data.get("conversation_id")
        or data.get("thread_id")
        or os.environ.get("CODEX_SESSION_ID")
        or "default_session"
    )

    ledger = Ledger()

    # If circuit breaker is TRIPPED, allow turn completion for escalation and root-cause reporting
    if ledger.get_state(session_id) == State.FAILURE_STAGE_2_TRIPPED.value:
        sys.stderr.write("[STOP GATE] Circuit breaker is TRIPPED (FAILURE_STAGE_2_TRIPPED); allowing turn completion for human escalation and root-cause reporting.\n")
        sys.exit(0)

    # 1. Check unverified code files
    unverified_files = [f for f in ledger.get_unverified_files(session_id) if is_code_file(f)]
    if unverified_files:
        file_list = ", ".join(unverified_files)
        sys.stderr.write(
            f"[STOP GATE REJECTED] Unverified modifications remain in session: {file_list}. "
            f"Run passing tests to verify modifications before completing the turn.\n"
        )
        sys.exit(1)

    # 2. Check walkthrough requirement only if modifications occurred
    if ledger.has_any_modifications(session_id) and not has_walkthrough_artifact(session_id, data, ledger):
        sys.stderr.write(
            "[STOP GATE REJECTED] Missing walkthrough or summary artifact. "
            "Author or update walkthrough.md to document verified changes before completing the turn.\n"
        )
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
