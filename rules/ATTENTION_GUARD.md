# Attention Guard Rules for Codex CLI & ChatGPT App

Attention Guard protects the agent's context window from Attention Dilution, prevents repetitive speculative trial-and-error loops, and ensures test verification before turn completion.

---

## 1. Two-Stage Anti-Looping Circuit Breaker

The plugin monitors command exit codes and enforces a strict Finite State Machine (FSM):

```
       +-------------------------------------------------------+
       |                                                       |
       v                                                       |
   [NORMAL]  -- (Test Failure) -->  [FAILURE_STAGE_1]          | (Test Pass)
       ^                                   |                   |
       |                             (2nd Failure)             |
       |                                   v                   |
       |                       [FAILURE_STAGE_2_TRIPPED]       |
       |                                   |                   |
       +--- (Transition) --- [RECOVERY_VERIFIED] <-------------+
```

### State Behaviors

1. **`NORMAL`**:
   - Healthy operational state.
   - All standard read, write, and command operations proceed normally.

2. **`FAILURE_STAGE_1` (Speculative Edit Barrier)**:
   - **Trigger**: Occurs immediately upon the first non-zero exit code of a test or build command.
   - **Enforcement**: Production file modifications are strictly blocked.
   - **Permitted Writes**: Only isolated test reproducers (`test_*`, `*_test.*`, `*Test.*`, `*.spec.*`) or diagnostic investigation files (`diagnosis.md`, `rca.md`, `*.log`) can be written or edited.
   - **Required Action**: Author an isolated reproducer that demonstrates the failure before touching production code.

3. **`FAILURE_STAGE_2_TRIPPED` (Hard Circuit Breaker)**:
   - **Trigger**: Occurs upon consecutive test or build failures (streak $\ge 2$).
   - **Enforcement**: All file mutations are completely blocked.
   - **Required Action**: Stop speculative loops immediately. Re-examine the root cause, inspect diagnostic logs, or reset the circuit breaker once a root-cause plan is formulated.

4. **`RECOVERY_VERIFIED`**:
   - **Trigger**: Occurs when a test execution passes (exit code 0).
   - **Enforcement**: Resets the failure streak to 0 and marks modified files as verified in the ledger.

---

## 2. Test-Driven Development (TDD) Reproducer Discipline

- **Defect Reproduction First**: Never attempt a bug fix without first writing an isolated reproducer test demonstrating the reported defect.
- **Zero Speculative Edits**: Never make guessing edits directly in production source code in response to test failures.
- **Single-Test Increments**: Focus on one failing test at a time: observe the failure, write minimal code to pass, verify clean pass, and refactor.

---

## 3. RTK Token Compression & Output Offloading

To protect context tokens from output bloat:

- **Command Wrapping**: The plugin automatically prefixes test and build commands with `rtk test` or `rtk err` to eliminate terminal noise.
- **Trace Offloading**: If command output exceeds 2,000 characters, Attention Guard offloads the full raw output to `$CODEX_HOME/diagnostics/<session_id>_test_failure.log` and injects a compact head/tail summary into the context.

---

## 4. Stop Quality Gate & Turn Verification

Before concluding a turn (`Stop` hook):

1. **Verification Check**: All file modifications made during the session must be verified by passing test runs. Turns with unverified code modifications are rejected.
2. **Walkthrough Requirement**: A `walkthrough.md` (or summary document) documenting the changes and test results must be present or updated.
