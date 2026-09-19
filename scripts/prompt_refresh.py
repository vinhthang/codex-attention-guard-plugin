import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from ledger import Ledger


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
    turn_count = ledger.increment_turn(session_id)
    state = ledger.get_state(session_id)

    should_inject = (turn_count % 5 == 0) or state.startswith("FAILURE_STAGE")

    if should_inject:
        reminder = (
            f"[ATTENTION GUARD REMINDER - State: {state}, Turn: {turn_count}]\n"
            "- Output Compression: Prefix test/build commands with 'rtk' to prevent token bloat.\n"
            "- Anti-Looping Circuit Breaker: Do NOT make speculative in-place edits on failure.\n"
            "- Root-Cause Isolation: Author an isolated test reproducer (test_*, *_test.*) or diagnostic doc before fixing code.\n"
            "- Quality Gate: Verify changes with passing tests and maintain walkthrough.md."
        )

        output = {
            "system_reminder": reminder,
            "additional_instructions": reminder,
            "turn_count": turn_count,
            "state": state,
        }
        ledger.record_turn_event(session_id, turn_count, "PROMPT_REFRESH_INJECTED", reminder)
        print(json.dumps(output))
    else:
        ledger.record_turn_event(session_id, turn_count, "PROMPT_REFRESH_PASSTHROUGH", "")
        print(json.dumps(data))

    sys.exit(0)


if __name__ == "__main__":
    main()
