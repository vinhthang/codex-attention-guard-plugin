import json
import os
import sys

# Ensure scripts directory is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from ledger import Ledger


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        data = json.loads(raw_input) if raw_input.strip() else {}
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
    ledger.init_session(session_id, metadata=data)
    sys.exit(0)


if __name__ == "__main__":
    main()
