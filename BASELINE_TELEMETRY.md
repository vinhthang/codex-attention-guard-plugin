# Attention Guard Telemetry Baseline Report

**Recorded Date**: 2026-09-20  
**Environment**: macOS (Apple Silicon), Codex CLI v0.149.1 (`~/.codex`), Google Antigravity (`~/.gemini/antigravity`)  
**Purpose**: Establish the pre-plugin baseline metrics across 314 Codex sessions to benchmark against a future evaluation period following the installation of `codex-attention-guard-plugin`.

---

## 1. Executive Summary & Telemetry Matrix

Telemetry was extracted directly from local databases:
- **Codex Source**: `~/.codex/thread_history_1.sqlite` (314 threads, 1,981 turns, 6,913 command executions).
- **Antigravity Source**: `~/.gemini/antigravity/attention_guard.db` and `~/.gemini/antigravity/brain/` (150 sampled sessions).

| Telemetry Metric | Codex Baseline <br>*(Pre-Installation)* | Antigravity Target <br>*(With Attention Guard)* | Benchmark Delta / Goal |
|---|---|---|---|
| **Average Command Output Size** | **14,385 chars** (~3,500 tokens) | **1,040 chars** (~250 tokens) | **13.8x reduction** |
| **Oversized Command Outputs (> 2 KB)** | **58.4%** (4,040 / 6,913) | **17.5%** (566 / 3,241) | **70% fewer** bulky outputs |
| **Max Single Command Output Spike** | **1,048,606 chars** (~260k tokens) | **4,121 chars** (~1k tokens) | **99.6% reduction** in catastrophic dumps |
| **Forced Context Compactions** | **156 times** | **0 times** | Eliminate context loss |
| **Total Command Output Characters** | **99,444,398 chars** | **5,428,056 chars** (filtered) | **~23.5M direct tokens saved** |
| **Cumulative Re-read Token Footprint** | **~443 Million tokens** | **~24 Million tokens** | **~419M cumulative context tokens saved** |
| **Multi-Failure Streaks ($\ge 2$ fails)** | **128 occurrences** | Capped by FSM | Containment to $\le 2$ |
| **Max Consecutive Failure Streak** | **10 failures in a row** | **4 failures** (FSM limit) | **60% shorter** recovery cycles |
| **Speculative In-Place Code Edits** | **141 occurrences** | **0** (658 active blocks) | Enforce reproducer / RCA first |
| **Unverified Commits (Team Audit)** | **88%** (15 / 17 commits) | **0%** (414 walkthrough gates) | 100% verified turns |

---

## 2. In-Depth Metric Analysis

### A. Context Window Protection & Token Waste
* **Direct Command Dumps**: In raw Codex usage, 58.4% of command executions dumped $> 2\text{KB}$ into the primary conversation window. Total output across 6,913 commands reached nearly **100 million characters** (~24.86M tokens).
* **Multi-Turn Context Amplification**: Because every conversation token is re-ingested on subsequent turns, oversized command outputs multiplied into an estimated **443 million cumulative input tokens**.
* **Cache Invalidation & Compaction**: Overwhelmed context windows forced Codex to trigger **`contextCompaction` 156 times**, wiping prompt caches and causing the agent to lose earlier instructions and architectural grounding.

### B. Anti-Looping & Circuit Breaker Metrics
* **Failure Volume**: 814 commands (11.8% of all commands) failed with non-zero exit codes.
* **Speculative In-Place Edits**: In **141 instances**, Codex immediately modified production code (`fileChange`) directly after a failed command, without authoring an isolated test reproducer or diagnosing root cause.
* **Failure Streaks**: 128 multi-failure streaks occurred, with the worst streak reaching **10 consecutive failed commands** (e.g. in Thread `01a037cd`).
* **Antigravity Comparison**: In Antigravity, Attention Guard's FSM clamped failure streaks to a maximum of 4 by issuing **658 `PRIMARY_TOOL_DENIED` blocks**, preventing speculative edits and enforcing root-cause investigation.

### C. Quality Gating & Verification Metrics
* **Axon Repository Audit**: Historical audit findings in `axon-sdlc/harnesses/codex/AGENTS.md` revealed that 88% of Codex-authored commits lacked verification evidence.
* **Antigravity Baseline**: Attention Guard enforced **414 `STOP_REQUESTED` quality gate checks**, rejecting turn completion until changes were verified with passing tests and documented in a walkthrough artifact.

---

## 3. Post-Installation Evaluation Protocol

After using Codex with `codex-attention-guard-plugin` for several days, run the automated comparison audit:

```bash
python3 /Users/thanghoang/github/codex-attention-guard-plugin/scripts/telemetry_audit.py --compare --since "2026-09-20"
```

The audit script will:
1. Parse all new thread turns in `~/.codex/thread_history_1.sqlite` created after the installation timestamp (`2026-09-20`).
2. Calculate:
   - Output token reduction percentage.
   - Percentage of commands exceeding 2 KB.
   - Number of context compaction events.
   - Consecutive failure streak lengths (target: $\le 2$).
   - Speculative edit occurrences (target: 0).
   - Stop quality gate compliance rate (target: 100%).
3. Print a side-by-side Before vs After delta report.
