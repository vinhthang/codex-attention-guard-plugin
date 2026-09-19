import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


def get_default_db_path() -> str:
    codex_home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    return os.path.join(codex_home, "thread_history_1.sqlite")


def date_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return int(dt.timestamp() * 1000)


def analyze_db(
    db_path: str,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None
) -> Dict[str, Any]:
    if not os.path.exists(db_path):
        return {
            "threads": 0,
            "turns": 0,
            "commands": 0,
            "total_chars": 0,
            "avg_chars": 0.0,
            "oversized_2kb": 0,
            "oversized_pct": 0.0,
            "max_spike": 0,
            "failed_commands": 0,
            "compactions": 0,
            "multi_failure_streaks": 0,
            "max_streak": 0,
            "speculative_edits": 0,
        }

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    time_clause = []
    params = []
    if start_ts is not None:
        time_clause.append("created_at_ms >= ?")
        params.append(start_ts)
    if end_ts is not None:
        time_clause.append("created_at_ms < ?")
        params.append(end_ts)

    where_str = ("WHERE " + " AND ".join(time_clause)) if time_clause else ""

    # Thread and Turn counts
    c.execute(f"SELECT COUNT(DISTINCT thread_id), COUNT(DISTINCT turn_id) FROM thread_items {where_str}", params)
    row = c.fetchone()
    threads_count = row[0] if row else 0
    turns_count = row[1] if row else 0

    # Commands
    cmd_where = f"WHERE item_type = 'commandExecution'" + (f" AND {' AND '.join(time_clause)}" if time_clause else "")
    c.execute(f"SELECT item_json FROM thread_items {cmd_where}", params)
    cmd_rows = c.fetchall()

    total_commands = len(cmd_rows)
    total_chars = 0
    oversized_2kb = 0
    max_spike = 0
    failed_commands = 0

    for (raw_json,) in cmd_rows:
        try:
            item = json.loads(raw_json)
        except Exception:
            continue
        out = item.get("aggregatedOutput") or ""
        length = len(out)
        total_chars += length
        if length > 2048:
            oversized_2kb += 1
        if length > max_spike:
            max_spike = length
        if item.get("exitCode", 0) != 0:
            failed_commands += 1

    avg_chars = (total_chars / total_commands) if total_commands else 0.0
    oversized_pct = (oversized_2kb / total_commands * 100.0) if total_commands else 0.0

    # Context Compactions
    compaction_where = f"WHERE item_type = 'contextCompaction'" + (f" AND {' AND '.join(time_clause)}" if time_clause else "")
    c.execute(f"SELECT COUNT(*) FROM thread_items {compaction_where}", params)
    comp_row = c.fetchone()
    compactions_count = comp_row[0] if comp_row else 0

    # Streaks and speculative edits ordered by thread
    seq_where = where_str
    c.execute(f"""
        SELECT thread_id, item_type, item_json 
        FROM thread_items 
        {seq_where}
        ORDER BY thread_id, rollout_ordinal, created_at_ms
    """, params)

    multi_failure_streaks = 0
    current_streak = 0
    max_streak = 0
    speculative_edits = 0
    last_failed = False
    current_thread = None

    for t_id, item_type, raw_json in c.fetchall():
        if t_id != current_thread:
            if current_streak >= 2:
                multi_failure_streaks += 1
            current_streak = 0
            last_failed = False
            current_thread = t_id

        if item_type == "commandExecution":
            try:
                item = json.loads(raw_json)
            except Exception:
                continue
            exit_code = item.get("exitCode", 0)
            if exit_code != 0:
                current_streak += 1
                if current_streak > max_streak:
                    max_streak = current_streak
                last_failed = True
            else:
                if current_streak >= 2:
                    multi_failure_streaks += 1
                current_streak = 0
                last_failed = False
        elif item_type == "fileChange":
            if last_failed:
                speculative_edits += 1
                last_failed = False

    if current_streak >= 2:
        multi_failure_streaks += 1

    conn.close()

    return {
        "threads": threads_count,
        "turns": turns_count,
        "commands": total_commands,
        "total_chars": total_chars,
        "avg_chars": avg_chars,
        "oversized_2kb": oversized_2kb,
        "oversized_pct": oversized_pct,
        "max_spike": max_spike,
        "failed_commands": failed_commands,
        "compactions": compactions_count,
        "multi_failure_streaks": multi_failure_streaks,
        "max_streak": max_streak,
        "speculative_edits": speculative_edits,
    }


def format_report(stats: Dict[str, Any], title: str = "Attention Guard Telemetry Report") -> str:
    lines = [
        f"# {title}",
        "",
        f"- **Analyzed Threads**: {stats['threads']:,}",
        f"- **Analyzed Turns**: {stats['turns']:,}",
        f"- **Commands Executed**: {stats['commands']:,}",
        f"- **Failed Commands**: {stats['failed_commands']:,}",
        f"- **Total Command Output**: {stats['total_chars']:,} chars (~{stats['total_chars'] // 4:,} tokens)",
        f"- **Average Output Size**: {stats['avg_chars']:.1f} chars",
        f"- **Oversized Outputs (> 2 KB)**: {stats['oversized_2kb']:,} ({stats['oversized_pct']:.1f}%)",
        f"- **Max Output Spike**: {stats['max_spike']:,} chars",
        f"- **Context Compactions**: {stats['compactions']:,}",
        f"- **Multi-Failure Streaks (>= 2)**: {stats['multi_failure_streaks']:,}",
        f"- **Max Consecutive Streak**: {stats['max_streak']}",
        f"- **Speculative Code Edits**: {stats['speculative_edits']:,}",
    ]
    return "\n".join(lines)


def format_comparison_table(before: Dict[str, Any], after: Dict[str, Any], split_date: str) -> str:
    def format_delta(b_val: float, a_val: float, is_pct: bool = False, lower_is_better: bool = True) -> str:
        if b_val == 0:
            return "N/A"
        reduction = ((b_val - a_val) / b_val) * 100.0
        if is_pct:
            return f"{a_val - b_val:+.1f}%"
        if lower_is_better and reduction > 0:
            return f"-{reduction:.1f}% reduction"
        return f"{((a_val - b_val) / b_val) * 100.0:+.1f}%"

    lines = [
        f"# Attention Guard Telemetry Comparison (Split: {split_date})",
        "",
        "| Telemetry Metric | Before Baseline | After Installation | Delta / Impact |",
        "|---|---|---|---|",
        f"| **Active Threads** | {before['threads']:,} | {after['threads']:,} | - |",
        f"| **Turns Analyzed** | {before['turns']:,} | {after['turns']:,} | - |",
        f"| **Commands Executed** | {before['commands']:,} | {after['commands']:,} | - |",
        f"| **Average Command Output** | {before['avg_chars']:.1f} chars | {after['avg_chars']:.1f} chars | {format_delta(before['avg_chars'], after['avg_chars'])} |",
        f"| **Oversized Outputs (> 2 KB)** | {before['oversized_pct']:.1f}% ({before['oversized_2kb']:,}) | {after['oversized_pct']:.1f}% ({after['oversized_2kb']:,}) | {format_delta(before['oversized_pct'], after['oversized_pct'], is_pct=True)} |",
        f"| **Max Single Output Spike** | {before['max_spike']:,} chars | {after['max_spike']:,} chars | {format_delta(before['max_spike'], after['max_spike'])} |",
        f"| **Forced Context Compactions** | {before['compactions']:,} | {after['compactions']:,} | {format_delta(before['compactions'], after['compactions'])} |",
        f"| **Multi-Failure Streaks (>= 2)** | {before['multi_failure_streaks']:,} | {after['multi_failure_streaks']:,} | {format_delta(before['multi_failure_streaks'], after['multi_failure_streaks'])} |",
        f"| **Max Consecutive Streak** | {before['max_streak']} | {after['max_streak']} | {format_delta(before['max_streak'], after['max_streak'])} |",
        f"| **Speculative In-Place Edits** | {before['speculative_edits']:,} | {after['speculative_edits']:,} | {format_delta(before['speculative_edits'], after['speculative_edits'])} |",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Attention Guard Telemetry Audit Tool for Codex CLI")
    parser.add_argument("--db", type=str, default=get_default_db_path(), help="Path to thread_history_1.sqlite")
    parser.add_argument("--baseline", action="store_true", help="Report baseline stats across entire database")
    parser.add_argument("--since", type=str, default=None, help="Filter stats since date (YYYY-MM-DD)")
    parser.add_argument("--compare", nargs="?", const="2026-09-20", default=None, help="Compare Before vs After date (default: 2026-09-20)")

    args = parser.parse_args()

    split_date = args.compare or args.since or "2026-09-20"

    if args.compare is not None:
        split_ms = date_to_ms(split_date)
        before_stats = analyze_db(args.db, end_ts=split_ms)
        after_stats = analyze_db(args.db, start_ts=split_ms)
        print(format_comparison_table(before_stats, after_stats, split_date))
    elif args.since:
        since_ms = date_to_ms(args.since)
        stats = analyze_db(args.db, start_ts=since_ms)
        print(format_report(stats, f"Attention Guard Telemetry Report (Since {args.since})"))
    else:
        # Default or --baseline
        stats = analyze_db(args.db)
        print(format_report(stats, "Attention Guard Telemetry Baseline Report"))


if __name__ == "__main__":
    main()
