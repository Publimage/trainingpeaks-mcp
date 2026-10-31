"""Isolated, reversible SQLite crash/restart canary for the existing ledger v1.

No TrainingPeaks client, network call, production database access, server restart,
or persistent write. A disposable child is killed mid-transaction with SIGKILL;
the parent proves SQLite rollback, restart, idempotence and re-open readback.
"""
from __future__ import annotations
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from ironman_state_store_v1 import DB_PATH, connect, digest, read_snapshot, record_verified_snapshot

LAB_JOB = "sqlite-crash-restart-isolated-lab-v1"
LAB_SOURCE = "technical:sqlite-v1:crash-restart-canary"
LAB_PROVIDER = "LOCAL-SQLITE-LAB-NO-PROVIDER"

def expected_rows():
    return [
        {"item_id": 91001, "relative_week": 1, "duration_min": 10,
         "provider_evidence_sha256": digest({"lab_item": 91001})},
        {"item_id": 91002, "relative_week": 1, "duration_min": 20,
         "provider_evidence_sha256": digest({"lab_item": 91002})},
    ]

def require_isolated(path: Path) -> None:
    path = path.resolve()
    if path == DB_PATH.resolve() or not path.name.endswith(".sqlite3"):
        raise RuntimeError("ISOLATED_DATABASE_REQUIRED")
    if "ironman-sqlite-crash-lab-" not in str(path.parent):
        raise RuntimeError("LAB_TEMP_DIRECTORY_REQUIRED")

def crash_child(path: Path) -> None:
    require_isolated(path)
    db = connect(path)
    db.execute("BEGIN IMMEDIATE")
    # A deliberately incomplete transaction. It must NEVER become visible.
    db.execute(
        "INSERT INTO jobs(job_id,source_ref,target_provider,target_plan,expected_items,state,verified_at,evidence_digest,schema_version) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (LAB_JOB, LAB_SOURCE, LAB_PROVIDER, 0, 2, "RUNNING", "test-utc", "UNCOMMITTED", 1),
    )
    db.execute(
        "INSERT INTO items(job_id,item_id,relative_week,duration_min,state,provider_evidence_sha256,verified_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (LAB_JOB, 91001, 1, 10, "RUNNING", digest({"lab_item": 91001}), "test-utc"),
    )
    print("UNCOMMITTED_TRANSACTION_REACHED", flush=True)
    os.kill(os.getpid(), signal.SIGKILL)
    raise RuntimeError("CHILD_MUST_NOT_SURVIVE_SIGKILL")

def run_isolated_canary() -> dict:
    with tempfile.TemporaryDirectory(prefix="ironman-sqlite-crash-lab-") as temporary:
        path = Path(temporary) / "isolated.sqlite3"
        require_isolated(path)
        db = connect(path)
        db.close()
        child = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--crash-child", str(path)],
            text=True, capture_output=True, timeout=15, check=False,
        )
        if child.returncode != -signal.SIGKILL or "UNCOMMITTED_TRANSACTION_REACHED" not in child.stdout:
            raise RuntimeError("CHILD_CRASH_NOT_PROVEN")
        # Restart using a fresh connection after the unclean child exit.
        db = connect(path)
        try:
            counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("jobs", "items", "events")}
            if any(counts.values()):
                raise RuntimeError("UNCOMMITTED_CHANGES_SURVIVED_CRASH")
            first = record_verified_snapshot(db, LAB_JOB, LAB_SOURCE, LAB_PROVIDER, 0, expected_rows())
            second = record_verified_snapshot(db, LAB_JOB, LAB_SOURCE, LAB_PROVIDER, 0, expected_rows())
            result = read_snapshot(db, LAB_JOB)
            if not first["created"] or second["created"] or result["event_count"] != 1:
                raise RuntimeError("DUPLICATE_ON_RETRY")
        finally:
            db.close()
        # Reopen separately, confirming committed state survives another process boundary.
        reopened = connect(path, read_only=True)
        try:
            after = read_snapshot(reopened, LAB_JOB)
        finally:
            reopened.close()
        if result != after or len(after["items"]) != 2:
            raise RuntimeError("RESTART_READBACK_MISMATCH")
        return {"stage": "DO_LEDGER_ISOLATED_CRASH_RESTART_PASS",
                "database": "temporary-isolated", "child_exit": child.returncode,
                "rolled_back": counts, "resumed_items": after["expected_items"],
                "event_count": after["event_count"], "idempotent_retry": True,
                "provider_writes": 0, "production_ledger_access": False,
                "service_restarted": False}

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--crash-child":
        crash_child(Path(sys.argv[2]))
    elif len(sys.argv) == 1:
        print(json.dumps(run_isolated_canary(), sort_keys=True), flush=True)
    else:
        raise SystemExit("INVALID_MODE")
