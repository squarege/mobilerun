#!/usr/bin/env python3
"""Reject staged workflow artifacts and secrets before they reach Git."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import PurePosixPath

_EXAMPLE_PARTS = {"example", "examples", "fixture", "fixtures", "testdata"}
_GATE_IMPLEMENTATION = "scripts/check_staged_privacy.py"
_PRIVATE_WORKFLOW_MARKERS = (
    re.compile(r"tonghuashun", re.IGNORECASE),
    re.compile(r"同花顺"),
    re.compile(r"\b300033\b"),
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?P<name>api[_-]?key|auth[_-]?token|access[_-]?token|password|passwd|"
    r"secret(?![_-]?id)|private[_-]?key)\s*[:=]\s*[\"']?(?P<value>[^\s,\"']+)",
    re.IGNORECASE,
)
_TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |)PRIVATE KEY-----"),
)
_LOCAL_PATH = re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+(?:/|\b)")
_DEVICE_SERIAL = re.compile(r"\bemulator-\d+\b")
_PLACEHOLDER = re.compile(
    r"^(?:null|none|false|true|stub|test|dummy|example|redacted|"
    r"your[-_]|<|\$\{|CHANGE_ME|changeme)",
    re.IGNORECASE,
)


def is_example_path(path: str) -> bool:
    return bool(_EXAMPLE_PARTS.intersection(PurePosixPath(path).parts))


def check_path(path: str) -> list[str]:
    """Return path violations; example/fixture paths are allowed."""
    parts = set(PurePosixPath(path).parts)
    if is_example_path(path):
        return []
    violations = []
    if "workflows" in parts:
        violations.append("workflow files must be kept out of the repository unless they are examples")
    if parts.intersection({"runs", "trajectories", "logs"}):
        violations.append("runtime artifacts must not be committed")
    if PurePosixPath(path).name in {
        "macro.json",
        "workflow.json",
        "journal.jsonl",
        "result.json",
        "repair_proposal.json",
    }:
        violations.append("generated workflow/runtime artifacts must not be committed")
    return violations


def _is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER.match(value.strip().strip("\"'")))


def check_text(path: str, text: str) -> list[str]:
    """Return privacy violations found in staged text."""
    violations: list[str] = []
    for marker in _PRIVATE_WORKFLOW_MARKERS:
        if marker.search(text):
            violations.append("contains a private workflow/app identifier")
            break

    if _LOCAL_PATH.search(text):
        violations.append("contains a local absolute user path")
    if _DEVICE_SERIAL.search(text):
        violations.append("contains a device-specific emulator serial")

    for pattern in _TOKEN_PATTERNS:
        if pattern.search(text):
            violations.append("contains a credential or private key pattern")
            break

    for match in _SECRET_ASSIGNMENT.finditer(text):
        value = match.group("value")
        if not _is_placeholder(value):
            violations.append(f"contains a non-placeholder {match.group('name')} value")
            break
    return violations


def staged_paths() -> list[str]:
    output = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        text=True,
    )
    return [line for line in output.splitlines() if line]


def staged_text(path: str) -> str | None:
    try:
        raw = subprocess.check_output(["git", "show", f":{path}"], stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return None
    if b"\x00" in raw:
        return None
    return raw.decode("utf-8", errors="replace")


def main() -> int:
    failures: list[tuple[str, str]] = []
    for path in staged_paths():
        for violation in check_path(path):
            failures.append((path, violation))
        text = staged_text(path)
        if text is not None and path != _GATE_IMPLEMENTATION:
            for violation in check_text(path, text):
                failures.append((path, violation))

    if failures:
        print("Privacy/workflow commit gate failed:", file=sys.stderr)
        for path, reason in failures:
            print(f"  - {path}: {reason}", file=sys.stderr)
        print(
            "Example/fixture paths are allowed; remove private artifacts or keep them local.",
            file=sys.stderr,
        )
        return 1
    print(f"Privacy/workflow commit gate passed ({len(staged_paths())} staged paths checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
