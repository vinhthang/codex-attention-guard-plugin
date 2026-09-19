import os
import re
from enum import Enum


class State(str, Enum):
    NORMAL = "NORMAL"
    FAILURE_STAGE_1 = "FAILURE_STAGE_1"
    FAILURE_STAGE_2_TRIPPED = "FAILURE_STAGE_2_TRIPPED"
    RECOVERY_VERIFIED = "RECOVERY_VERIFIED"


class Event(str, Enum):
    TEST_FAILURE = "TEST_FAILURE"
    TEST_PASS = "TEST_PASS"
    REPRODUCER_CREATED = "REPRODUCER_CREATED"
    RESET = "RESET"


def is_test_or_diagnostic_file(file_path: str) -> bool:
    if not file_path:
        return False
    
    basename = os.path.basename(file_path)
    lower_name = basename.lower()
    norm_path = file_path.replace("\\", "/").lower()

    # Diagnostic doc patterns
    if lower_name in ("diagnosis.md", "rca.md", "root_cause.md", "investigation.md"):
        return True
    if lower_name.startswith("diagnosis") or lower_name.startswith("rca_") or lower_name.startswith("rca-"):
        return True
    if lower_name.endswith(".log"):
        return True

    # Test / Reproducer patterns:
    # 1. test_* or *_test.*
    if re.match(r"^test_.*\..+$", basename, re.IGNORECASE):
        return True
    if re.match(r"^.+_test\..+$", basename, re.IGNORECASE):
        return True

    # 2. *Test.* (e.g. UserServiceTest.java)
    if re.search(r"Test\.[a-zA-Z0-9]+$", basename):
        return True

    # 3. *.spec.* or *.test.* (e.g. app.spec.ts, login.test.jsx)
    if re.search(r"\.(spec|test)\.[a-zA-Z0-9]+$", lower_name):
        return True

    # 4. In a dedicated tests directory with test in filename
    if any(d in norm_path for d in ["/tests/", "/test/", "/__tests__/"]):
        return True

    return False


def can_mutate_file(state: str, file_path: str) -> tuple[bool, str]:
    if state in (State.NORMAL.value, State.RECOVERY_VERIFIED.value):
        return True, ""

    if state == State.FAILURE_STAGE_1.value:
        if is_test_or_diagnostic_file(file_path):
            return True, ""
        return (
            False,
            f"Speculative edit blocked in FAILURE_STAGE_1: '{file_path}' is not a test reproducer "
            f"(test_*, *_test.*, *Test.*, *.spec.*) or diagnostic doc (diagnosis.md, rca.md, *.log)."
        )

    if state == State.FAILURE_STAGE_2_TRIPPED.value:
        return (
            False,
            f"Circuit breaker TRIPPED (FAILURE_STAGE_2_TRIPPED): Consecutive test failures. "
            f"All file mutations are blocked. Stop speculative modifications, isolate root cause, "
            f"and reset the circuit breaker."
        )

    return True, ""


class AttentionGuardFSM:
    def __init__(self, initial_state: str = State.NORMAL.value, failure_streak: int = 0):
        self.state = initial_state
        self.failure_streak = failure_streak

    def transition(self, event: str, context: dict = None) -> tuple[str, str]:
        """
        Transitions the state machine given an event.
        Returns (new_state, transition_message).
        """
        context = context or {}

        if event == Event.RESET.value:
            self.state = State.NORMAL.value
            self.failure_streak = 0
            return self.state, "Reset to NORMAL state, streak cleared."

        if event == Event.TEST_FAILURE.value:
            self.failure_streak += 1
            if self.failure_streak == 1:
                self.state = State.FAILURE_STAGE_1.value
                return self.state, "First failure: transitioned to FAILURE_STAGE_1. Enforcing reproducer discipline."
            else:
                self.state = State.FAILURE_STAGE_2_TRIPPED.value
                return self.state, f"Consecutive failure (streak={self.failure_streak}): circuit breaker TRIPPED (FAILURE_STAGE_2_TRIPPED)."

        if event == Event.TEST_PASS.value:
            self.failure_streak = 0
            if self.state in (State.FAILURE_STAGE_1.value, State.FAILURE_STAGE_2_TRIPPED.value):
                self.state = State.RECOVERY_VERIFIED.value
                return self.state, "Test passed: transitioned to RECOVERY_VERIFIED. Modifications verified."
            elif self.state == State.RECOVERY_VERIFIED.value:
                self.state = State.NORMAL.value
                return self.state, "Transitioned from RECOVERY_VERIFIED to NORMAL."
            else:
                self.state = State.NORMAL.value
                return self.state, "Test passed in NORMAL state."

        if event == Event.REPRODUCER_CREATED.value:
            if self.state == State.FAILURE_STAGE_1.value:
                return self.state, "Reproducer created in FAILURE_STAGE_1. Proceed to run reproducer test."
            elif self.state == State.FAILURE_STAGE_2_TRIPPED.value:
                return self.state, "Reproducer created while tripped. Run reproducer to confirm reproduction."
            return self.state, "Reproducer created."

        return self.state, f"Unhandled event '{event}' in state '{self.state}'."
