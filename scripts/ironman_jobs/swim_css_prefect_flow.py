"""One-off Prefect process-worker wrapper for the reviewed CSS sample.

The child uses the existing Google-capable venv; Prefect's venv is never
modified. A negative workout QA result is evidence, not publishing approval.
No schedule or task-level retries.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import subprocess

from prefect import flow, task
from scripts.ironman_jobs.swim_css_live_run import validate_child_output

ROOT = Path(__file__).resolve().parents[2]
CHILD_PYTHON = "/opt/ironman-prefect/drive-reader/venv/bin/python"


@task(name="audit-reviewed-css2200-once", retries=0, log_prints=False)
def audit_css_task() -> dict:
    user = pwd.getpwnam("ironmanprefect")
    if os.getuid() != user.pw_uid or os.getuid() == 0:
        raise RuntimeError("WRONG_PREFECT_WORKER_USER")
    env = {
        "HOME": user.pw_dir,
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": f"{ROOT}:{ROOT / 'src'}",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    try:
        response = subprocess.run(
            [CHILD_PYTHON, "-B", "-m", "scripts.ironman_jobs.swim_css_live_run"],
            cwd=ROOT, env=env, text=True, capture_output=True,
            timeout=180, check=False,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("SWIM_CSS_CHILD_TIMEOUT") from None
    if response.returncode != 0:
        # Never return child stderr: it could contain provider or source data.
        try:
            stop = json.loads(response.stdout)
            code = stop.get("code", "UNKNOWN")
        except (json.JSONDecodeError, TypeError):
            code = "NO_SAFE_CODE"
        raise RuntimeError(f"SWIM_CSS_CHILD_FAILED:{code}")
    try:
        data = json.loads(response.stdout)
    except (json.JSONDecodeError, TypeError):
        raise RuntimeError("SWIM_CSS_CHILD_JSON_INVALID") from None
    return validate_child_output(data)


@flow(name="ironman-swim-css-audit-v1", retries=0, log_prints=False)
def swim_css_flow() -> dict:
    return audit_css_task()
