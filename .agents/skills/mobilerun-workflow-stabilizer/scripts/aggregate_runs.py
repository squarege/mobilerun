#!/usr/bin/env python3
"""Aggregate Mobilerun workflow result.json files into a Markdown batch report."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

PASS_STATUSES = {"MACRO_SUCCESS", "RECOVERED_AND_RESUMED"}
STRICT_STATUS = "MACRO_SUCCESS"


def load_results(root: Path) -> list[tuple[str, dict]]:
    rows = []
    for path in sorted(root.glob("runs/*/result.json")):
        try:
            rows.append((path.parent.name, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError) as exc:
            rows.append((path.parent.name, {"status": "INFRASTRUCTURE_ERROR", "failure_reason": str(exc)}))
    return rows


def build_report(workflow_root: Path, rows: list[tuple[str, dict]], requested: int) -> str:
    workflow_id = workflow_root.name
    active = None
    active_path = workflow_root / "active.json"
    if active_path.exists():
        try:
            active = json.loads(active_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            active = None

    completed = len(rows)
    strict = sum(result.get("status") == STRICT_STATUS for _, result in rows)
    effective = sum(result.get("status") in PASS_STATUSES for _, result in rows)
    recovered = sum(result.get("status") == "RECOVERED_AND_RESUMED" for _, result in rows)
    failed = sum(result.get("status") in {"FAILED", "BLOCKED", "UNKNOWN_OUTCOME"} for _, result in rows)
    llm_calls = sum(int(result.get("llm_calls") or 0) for _, result in rows)
    durations = [float(result["duration_seconds"]) for _, result in rows if result.get("duration_seconds") is not None]

    def rate(value: int, denominator: int) -> str:
        return f"{value / denominator * 100:.1f}%" if denominator else "n/a"

    lines = [
        f"# {workflow_id} batch report",
        "",
        "## Summary",
        f"- Requested runs: {requested}",
        f"- Result files found: {completed}",
        f"- Active version: {(active or {}).get('version', 'unknown')}",
        f"- Strict deterministic pass rate: {strict}/{requested} ({rate(strict, requested)})",
        f"- Supervised effective pass rate: {effective}/{requested} ({rate(effective, requested)})",
        f"- Recovered and resumed: {recovered}",
        f"- Failed/blocked/unknown: {failed}",
        f"- Total LLM calls: {llm_calls}",
        f"- Average duration: {statistics.mean(durations):.1f}s" if durations else "- Average duration: unavailable",
        "",
        "## Runs",
        "| Run ID | Status | Steps | LLM calls | Recoveries | Failure |",
        "|---|---|---:|---:|---:|---|",
    ]
    for run_id, result in rows[-requested:]:
        failure = str(result.get("failure_reason") or "") .replace("|", "\\|")
        lines.append(
            f"| `{run_id}` | `{result.get('status', 'UNKNOWN')}` | "
            f"{result.get('steps_completed', 'n/a')}/{result.get('total_steps', 'n/a')} | "
            f"{result.get('llm_calls', 0)} | {result.get('recovery_attempts', 0)} | {failure} |"
        )
    lines += [
        "",
        "## Interpretation",
        "- `MACRO_SUCCESS` counts as a strict deterministic pass.",
        "- `RECOVERED_AND_RESUMED` counts only in the supervised effective pass rate.",
        "- `FALLBACK_COMPLETED` is not counted as workflow recovery.",
        "- Missing result files are not silently converted into passes.",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-root", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--requested", type=int, default=None)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    rows = load_results(args.workflow_root)
    requested = args.requested or args.limit
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_report(args.workflow_root, rows, requested), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
