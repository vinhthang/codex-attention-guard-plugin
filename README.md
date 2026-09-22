# Codex Attention Guard Plugin

Context window protection, hybrid RTK token compression, two-stage anti-looping circuit breaker, and turn verification gating for Codex CLI and ChatGPT app.

---

## 1. Overview & Key Capabilities

Codex Attention Guard protects the agent's context window from Attention Dilution and repetitive looping failure modes:

- **Hybrid RTK Token Compression**: Intercepts shell test/build runners (`pytest`, `cargo test`, `mvn`, `npm test`, `vitest`, `go test`, `dotnet test`) and automatically wraps them with `rtk test` or `rtk err`.
- **2KB Diagnostic Trace Offloading**: Commands producing $> 2\text{ KB}$ outputs (~500 tokens) are offloaded to disk:
  - **Saved to Disk**: 100% of the raw, unabridged output is saved to `$CODEX_HOME/diagnostics/<session_id>_test_failure.log`.
  - **Returned to Prompt**: A compact ~1 KB summary (head 500 chars + log file pointer + tail 500 chars showing the failing assertion), saving ~95% of output tokens while ensuring deep stack frames remain accessible via `read_file` or `grep`.
- **Two-Stage Anti-Looping Circuit Breaker**:
  - `FAILURE_STAGE_1`: Triggered on 1st test/build failure. Blocks speculative edits to production files; permits only test reproducers (`test_*`, `*_test.*`, `*Test.*`, `*.spec.*`) or diagnostic investigation files (`diagnosis.md`, `rca.md`, `*.log`).
  - `FAILURE_STAGE_2_TRIPPED`: Triggered on consecutive failure ($\ge 2$). Hard-blocks all file mutations until reset or root cause is isolated.
  - `RECOVERY_VERIFIED`: Triggered when tests pass, verifying changes and resetting failure streaks.
- **Turn Quality Gating**: `Stop` hook validates that no unverified file modifications remain in the session and that a walkthrough or summary artifact (`walkthrough.md`) has been created or updated.

---

## 2. Architecture & Lifecycle Hooks

The plugin integrates seamlessly with Codex CLI via `.codex-plugin/plugin.json` and `hooks/hooks.json`:

| Hook | Handler Script | Description |
|---|---|---|
| `SessionStart` | `scripts/session_init.py` | Initializes session state and metadata in SQLite ledger |
| `UserPromptSubmit` | `scripts/prompt_refresh.py` | Refreshes rules every 5 turns or during failure stages |
| `PreToolUse` | `scripts/pre_tool_guard.py` | RTK command wrapping; blocks speculative file edits in failure states |
| `PostToolUse` | `scripts/post_tool_guard.py` | Evaluates command results; offloads $>2\text{KB}$ traces; transitions FSM |
| `Stop` | `scripts/stop_quality_gate.py` | Rejects turn conclusion if unverified edits or missing walkthrough |

### Persistent Ledger

State and telemetry are persisted in SQLite at `$CODEX_HOME/attention_guard.sqlite` (or `~/.codex/attention_guard.sqlite`, configurable via `ATTENTION_GUARD_DB`):
- `sessions`: Active state, turn counter, failure streak, and session metadata.
- `file_modifications`: Modified files, timestamp, verification status (`0`=unverified, `1`=verified).
- `failure_events`: Failing commands, exit codes, output summaries, offloaded log paths.
- `turn_events`: Tool calls and prompt refresh events.

---

## 3. Configuration & Installation

### Option A: Local Marketplace Registration in `~/.codex/config.toml`

Add the local repository to your `~/.codex/config.toml`:

```toml
[marketplaces.local-plugins]
source_type = "local"
source = "/Users/thanghoang/github"

[plugins."attention-guard@local-plugins"]
enabled = true
```

### Option B: Symlink / Direct Plugin Installation

Link directly into Codex plugins directory:

```bash
mkdir -p ~/.codex/plugins/cache/local/attention-guard/0.1.0
cp -r /Users/thanghoang/github/codex-attention-guard-plugin/* ~/.codex/plugins/cache/local/attention-guard/0.1.0/
```

Or enable hooks directly in `~/.codex/hooks.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 -I /Users/thanghoang/github/codex-attention-guard-plugin/scripts/session_init.py",
            "timeout": 10
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 -I /Users/thanghoang/github/codex-attention-guard-plugin/scripts/pre_tool_guard.py",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 -I /Users/thanghoang/github/codex-attention-guard-plugin/scripts/post_tool_guard.py",
            "timeout": 10
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 -I /Users/thanghoang/github/codex-attention-guard-plugin/scripts/stop_quality_gate.py",
            "timeout": 10
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 -I /Users/thanghoang/github/codex-attention-guard-plugin/scripts/prompt_refresh.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

---

## 4. Telemetry Audit Tool

A dedicated telemetry analysis CLI inspects your local Codex history database (`~/.codex/thread_history_1.sqlite`):

### Run Baseline Report
```bash
python3 scripts/telemetry_audit.py --baseline
```

### Run Before vs After Comparison
```bash
python3 scripts/telemetry_audit.py --compare 2026-09-20
```

### Run Since Specific Date
```bash
python3 scripts/telemetry_audit.py --since 2026-09-20
```

---

## 5. Development & Testing

Run unit tests using pytest:

```bash
rtk pytest -v
```
