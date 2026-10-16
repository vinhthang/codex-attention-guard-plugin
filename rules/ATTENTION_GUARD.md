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
   - **Permitted Writes**: Test reproducers (`test_*`, `*_test.*`, `*Test.*`, `*.spec.*`), diagnostic investigation files (`diagnosis.md`, `rca.md`, `*.log`), and markdown documentation (`*.md`, `docs/**`).
   - **Required Action**: Author an isolated reproducer that demonstrates the failure before touching production code.

3. **`FAILURE_STAGE_2_TRIPPED` (Hard Circuit Breaker)**:
   - **Trigger**: Occurs upon consecutive test or build failures (streak $\ge 2$).
   - **Enforcement**: Code and test modifications are blocked. Diagnostic docs (`diagnosis.md`, `rca.md`, `*.log`) and markdown documentation (`*.md`, `docs/**`) remain permitted to isolate root cause.
   - **Required Action**: Stop speculative loops immediately. Author diagnostic documentation to isolate root cause, escalate to human or peer review, and reset the circuit breaker once a root-cause plan is formulated.

4. **`RECOVERY_VERIFIED`**:
   - **Trigger**: Occurs when a test execution passes (exit code 0).
   - **Enforcement**: Resets the failure streak to 0 and marks modified files as verified in the ledger.

---

## 2. Test-Driven Development (TDD) Reproducer Discipline

- **Defect Reproduction First**: Never attempt a bug fix without first writing an isolated reproducer test demonstrating the reported defect.
- **Zero Speculative Edits**: Never make guessing edits directly in production source code in response to test failures.
- **Single-Test Increments**: Focus on one failing test at a time: observe the failure, write minimal code to pass, verify clean pass, and refactor.

---

## 3. RTK Token Compression

To protect context tokens from output bloat:

- **Command Wrapping**: The plugin automatically prefixes test and build commands with `rtk test` or `rtk err` to eliminate terminal noise and isolate failing assertions.
- **Zero Arbitrary Truncation**: Token compression is handled upstream by RTK command prefixing without arbitrary character caps or trace offloading, preserving complete diagnostic output fidelity.

---

## 4. Stop Quality Gate & Turn Verification

Before concluding a turn (`Stop` hook):

1. **Circuit Breaker Tripped Escalation**: If the circuit breaker is TRIPPED (`FAILURE_STAGE_2_TRIPPED`), the gate allows turn completion to enable human escalation and root-cause reporting.
2. **Code Verification Check**: Only modified code files require passing test verification before concluding a turn. Non-code files (markdown documentation, plain text, configuration/data files) do not block completion without tests.
3. **Walkthrough Requirement**: When modifications occur, a `walkthrough.md` (or summary document) documenting the changes must be present or updated. Read-only turns with zero file modifications pass cleanly without requiring a walkthrough.
4. **Bypass Overrides**: Direct escalation questions or commands with bypass/force flags (`ATTENTION_GUARD_BYPASS=1`, payload `bypass`/`force`) bypass the gate.
