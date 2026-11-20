"""Ruff regression gate: block NEW findings without hiding inherited findings.

The staging branch currently has lint debt. Compare each diagnostic tuple against
the exact PR base (or previous push), requiring non-increasing counts per type.
This does not mark the baseline clean, and never suppresses a new diagnostic.
"""
from __future__ import annotations

import collections
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def command(argv: list[str], cwd: Path = ROOT) -> str:
    proc = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    if proc.returncode:
        raise RuntimeError(f"{' '.join(argv)} failed: {proc.stderr.strip()[:350]}")
    return proc.stdout


def lint(cwd: Path) -> collections.Counter[tuple[str, str, str]]:
    proc = subprocess.run(
        ["ruff", "check", "src/", "--output-format=json"],
        cwd=cwd, text=True, capture_output=True, check=False,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError("Ruff invocation failed: " + proc.stderr[:350])
    raw = json.loads(proc.stdout)
    counts: collections.Counter[tuple[str, str, str]] = collections.Counter()
    for issue in raw:
        path = Path(issue["filename"]).resolve().relative_to(cwd.resolve()).as_posix()
        counts[(path, str(issue["code"]), str(issue["message"]))] += 1
    return counts


def main() -> int:
    base = os.getenv("RUFF_BASE_SHA", "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", base) or set(base) == {"0"}:
        base = "HEAD^"
    print("Ruff baseline ref:", base, flush=True)
    if base != "HEAD^":
        command(["git", "fetch", "--no-tags", "origin", base])
    with tempfile.TemporaryDirectory(prefix="tp-ruff-baseline-") as directory:
        other = Path(directory)
        command(["git", "worktree", "add", "--detach", str(other), base])
        try:
            previous = lint(other)
            current = lint(ROOT)
        finally:
            command(["git", "worktree", "remove", "--force", str(other)])
    new = current - previous
    print(f"Ruff inherited={sum(previous.values())} current={sum(current.values())} new={sum(new.values())}")
    for (path, code, message), count in sorted(new.items()):
        print(f"NEW {count}x {path} {code}: {message}")
    if new:
        print("FAIL: source introduces Ruff diagnostics not in the exact base.")
        return 1
    print("PASS: zero new Ruff diagnostics. Inherited diagnostics remain an open cleanup.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"CI ERROR (no waiver): {exc}", file=sys.stderr)
        raise SystemExit(2)
