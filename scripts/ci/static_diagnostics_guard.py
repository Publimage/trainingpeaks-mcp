"""No-new-static-diagnostics gate for legacy code.

Comparisons use the PR base (or previous push) and exact diagnostic tuple
(module, error code, message). Existing Ruff/mypy debt is reported, not waived
indiscriminately: new findings of either type fail the build.
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def run(args: list[str], cwd: Path, allowed: tuple[int, ...] = (0,)) -> str:
    p = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if p.returncode not in allowed:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(args)}: {p.stderr[:500]}")
    return p.stdout


def ruff_errors(repo: Path) -> Counter[tuple[str, str, str]]:
    raw = json.loads(run(["ruff", "check", "src/", "--output-format=json"], repo, (0, 1)))
    errors: Counter[tuple[str, str, str]] = Counter()
    for x in raw:
        name = Path(x["filename"])
        if not name.is_absolute():
            name = repo / name
        relative = name.resolve().relative_to(repo.resolve()).as_posix()
        errors[(relative, str(x["code"]), str(x["message"]))] += 1
    return errors


def mypy_errors(repo: Path) -> Counter[tuple[str, str, str]]:
    raw = run(["mypy", "src/", "--no-incremental", "--show-error-codes"], repo, (0, 1))
    errors: Counter[tuple[str, str, str]] = Counter()
    rx = re.compile(r"^(src/[^:]+):\\d+(?::\\d+)?: error: (.*?)(?: \\[([^\\]]+)\\])?$")
    for line in raw.splitlines():
        if ": error:" in line:
            m = rx.match(line)
            if not m:
                raise RuntimeError("Unrecognized mypy error record: " + line[:300])
            errors[(m.group(1), m.group(3) or "unknown", m.group(2))] += 1
    return errors


def main() -> int:
    sha = os.getenv("STATIC_BASE_SHA", "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or set(sha) == {"0"}:
        sha = "HEAD^"
    print("Static baseline:", sha, flush=True)
    if sha != "HEAD^":
        run(["git", "fetch", "--no-tags", "origin", sha], ROOT)

    with tempfile.TemporaryDirectory(prefix="tp-ci-base-") as dirname:
        base = Path(dirname)
        run(["git", "worktree", "add", "--detach", str(base), sha], ROOT)
        try:
            pairs = [
                ("Ruff", ruff_errors(base), ruff_errors(ROOT)),
                ("mypy", mypy_errors(base), mypy_errors(ROOT)),
            ]
        finally:
            run(["git", "worktree", "remove", "--force", str(base)], ROOT)

    failures = False
    for label, before, after in pairs:
        new = after - before
        print(f"{label}: inherited={sum(before.values())}; current={sum(after.values())}; new={sum(new.values())}")
        for (path, code, message), count in sorted(new.items()):
            failures = True
            print(f"NEW {label} {count}x {path}: [{code}] {message}")
    if failures:
        print("FAIL: source adds new Ruff/mypy errors relative to its exact base.")
        return 1
    print("PASS: no new lint or type errors (inherited issues remain recorded).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"CI setup/error: {exc}", file=sys.stderr)
        raise SystemExit(2)
