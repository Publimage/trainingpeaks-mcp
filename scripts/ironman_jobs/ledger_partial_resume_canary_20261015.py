"""Isolated partial-job recovery canary on IRONMAN SQLite schema v1.

All writes are to TWO throwaway SQLite files below a private tempfile root.
One represents the ledger; the other SIMULATES an external provider. There
are no TrainingPeaks imports/calls, production-ledger reads, or service restarts.
This is a test adapter, not a production orchestrator or real-provider proof.
"""
from __future__ import annotations
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from ironman_state_store_v1 import DB_PATH, connect, digest

JOB = "ironman-sqlite-isolated-partial-resume-20261015-v1"
SOURCE = "technical-lab:sqlite-v1:checkpoint-and-ambiguous-outcome"
PROVIDER = "SIMULATED-EXTERNAL-SQLITE-NO-TRAININGPEAKS"
PREFIX = "ironman-sqlite-resume-lab-"
TASKS = ((93001, 1, 10), (93002, 1, 20), (93003, 2, 30), (93004, 2, 40))
EXPECTED = {item: digest({"job": JOB, "item_id": item, "week": week, "minutes": minutes})
            for item, week, minutes in TASKS}


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def lab_paths(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("LAB_ROOT_INVALID")
    resolved = root.resolve()
    if (resolved.parent != Path(tempfile.gettempdir()).resolve()
            or not resolved.name.startswith(PREFIX)):
        raise RuntimeError("ONLY_DIRECT_TEMPORARY_LAB_ROOT_ALLOWED")
    ledger = resolved / "ledger.sqlite3"
    external = resolved / "simulated_external.sqlite3"
    if (ledger.resolve() == DB_PATH.resolve()
            or external.resolve() == DB_PATH.resolve()
            or ledger.is_symlink() or external.is_symlink()):
        raise RuntimeError("PRODUCTION_LEDGER_OR_SYMLINK_FORBIDDEN")
    return ledger, external


def manifest_hash():
    return digest({"job": JOB, "source": SOURCE, "provider": PROVIDER, "tasks": TASKS})


def external_connect(root):
    _, path = lab_paths(root)
    db = sqlite3.connect(path, timeout=10)
    os.chmod(path, 0o600)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("CREATE TABLE IF NOT EXISTS objects (item_id INTEGER PRIMARY KEY, evidence TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS effects (seq INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL UNIQUE)")
    db.commit()
    return db


def external_read(root, item):
    db = external_connect(root)
    try:
        hit = db.execute("SELECT evidence FROM objects WHERE item_id=?", (item,)).fetchone()
        return hit[0] if hit else None
    finally:
        db.close()


def external_create(root, item, evidence=None):
    """Simulated remote effect, COMMITTED independently of the ledger."""
    if item not in EXPECTED:
        raise RuntimeError("UNKNOWN_TASK")
    db = external_connect(root)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO objects(item_id,evidence) VALUES(?,?)",
                   (item, evidence if evidence is not None else EXPECTED[item]))
        db.execute("INSERT INTO effects(item_id) VALUES(?)", (item,))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def count_external(root):
    db = external_connect(root)
    try:
        return db.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
    finally:
        db.close()


def state(root):
    ledger, _ = lab_paths(root)
    db = connect(ledger, read_only=True)
    try:
        job = db.execute("SELECT state,source_ref,target_provider,target_plan,expected_items,evidence_digest FROM jobs WHERE job_id=?",
                         (JOB,)).fetchone()
        if job != ("RUNNING", SOURCE, PROVIDER, 0, len(TASKS), manifest_hash()) and job != (
                "DONE_VERIFIED", SOURCE, PROVIDER, 0, len(TASKS), manifest_hash()):
            raise RuntimeError("JOB_MANIFEST_OR_STATE_DRIFT")
        items = db.execute("SELECT item_id,relative_week,duration_min,state,provider_evidence_sha256 FROM items WHERE job_id=? ORDER BY item_id", (JOB,)).fetchall()
        if len(items) != len(TASKS):
            raise RuntimeError("TASK_COUNT_DRIFT")
        for got, (item, week, minutes) in zip(items, TASKS):
            if got[:3] != (item, week, minutes) or got[4] != EXPECTED[item]:
                raise RuntimeError("TASK_FINGERPRINT_DRIFT")
        events = db.execute("SELECT COUNT(*) FROM events WHERE job_id=?", (JOB,)).fetchone()[0]
        return {"job": job[0], "items": {row[0]: row[3] for row in items}, "events": events}
    finally:
        db.close()


def register(root):
    ledger, _ = lab_paths(root)
    db = connect(ledger)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO jobs(job_id,source_ref,target_provider,target_plan,expected_items,state,verified_at,evidence_digest,schema_version) VALUES(?,?,?,?,?,?,?,?,?)",
                   (JOB, SOURCE, PROVIDER, 0, len(TASKS), "RUNNING", utc(), manifest_hash(), 1))
        for item, week, minutes in TASKS:
            db.execute("INSERT INTO items(job_id,item_id,relative_week,duration_min,state,provider_evidence_sha256,verified_at) VALUES(?,?,?,?,?,?,?)",
                       (JOB, item, week, minutes, "PENDING", EXPECTED[item], utc()))
        db.execute("INSERT INTO events(job_id,kind,at_utc,details_sha256) VALUES(?,?,?,?)",
                   (JOB, "JOB_REGISTERED", utc(), manifest_hash()))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    ex = external_connect(root)
    ex.close()


def transition(root, item, target, event_kind):
    if target not in ("RUNNING", "DONE_VERIFIED") or item not in EXPECTED:
        raise RuntimeError("TRANSITION_NOT_ALLOWED")
    ledger, _ = lab_paths(root)
    db = connect(ledger)
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT state,provider_evidence_sha256 FROM items WHERE job_id=? AND item_id=?",
                         (JOB, item)).fetchone()
        if row is None or row[1] != EXPECTED[item]:
            raise RuntimeError("TRANSITION_FINGERPRINT_MISMATCH")
        previous = row[0]
        allowed = ((previous == "PENDING" and target == "RUNNING")
                   or (previous in ("PENDING", "RUNNING") and target == "DONE_VERIFIED"))
        if previous == target == "DONE_VERIFIED":
            db.commit()
            return False
        if not allowed:
            raise RuntimeError("ILLEGAL_STATE_TRANSITION")
        if target == "DONE_VERIFIED" and external_read(root, item) != EXPECTED[item]:
            raise RuntimeError("REMOTE_READBACK_REQUIRED")
        db.execute("UPDATE items SET state=?,verified_at=? WHERE job_id=? AND item_id=?",
                   (target, utc(), JOB, item))
        db.execute("INSERT INTO events(job_id,kind,at_utc,details_sha256) VALUES(?,?,?,?)",
                   (JOB, event_kind, utc(), digest({"item": item, "from": previous, "to": target})))
        if target == "DONE_VERIFIED":
            remaining = db.execute("SELECT COUNT(*) FROM items WHERE job_id=? AND state!='DONE_VERIFIED'", (JOB,)).fetchone()[0]
            if remaining == 0:
                db.execute("UPDATE jobs SET state=?,verified_at=? WHERE job_id=? AND state='RUNNING'",
                           ("DONE_VERIFIED", utc(), JOB))
                db.execute("INSERT INTO events(job_id,kind,at_utc,details_sha256) VALUES(?,?,?,?)",
                           (JOB, "JOB_DONE_VERIFIED", utc(), manifest_hash()))
        db.commit()
        return True
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def seed_and_crash(root):
    for item in (93001, 93004):
        transition(root, item, "RUNNING", "START")
        external_create(root, item)
        transition(root, item, "DONE_VERIFIED", "VERIFIED")
    transition(root, 93002, "RUNNING", "START")
    external_create(root, 93002)
    print("CRASH_AFTER_EXTERNAL_COMMIT_BEFORE_LEDGER_ACK", flush=True)
    os.kill(os.getpid(), signal.SIGKILL)
    raise RuntimeError("SIGKILL_DID_NOT_EXECUTE")


def resume(root):
    current = state(root)
    before = count_external(root)
    counts = {"skipped_verified": 0, "reconciled_uncertain": 0, "new_simulated_writes": 0}
    # Fail closed before any mutations: every existing remote object must match.
    for item, *_ in TASKS:
        remote = external_read(root, item)
        if remote is not None and remote != EXPECTED[item]:
            raise RuntimeError("PROVIDER_FINGERPRINT_MISMATCH")
        if current["items"][item] == "DONE_VERIFIED" and remote != EXPECTED[item]:
            raise RuntimeError("DONE_ITEM_REMOTE_EVIDENCE_MISSING")
    for item, *_ in TASKS:
        row_state = current["items"][item]
        remote = external_read(root, item)  # Every decision begins with readback.
        if row_state == "DONE_VERIFIED":
            counts["skipped_verified"] += 1
            continue
        if row_state not in ("PENDING", "RUNNING"):
            raise RuntimeError("FAIL_CLOSED_UNKNOWN_ITEM_STATE")
        if remote == EXPECTED[item]:
            transition(root, item, "DONE_VERIFIED", "RECOVERED_BY_READBACK")
            counts["reconciled_uncertain"] += 1
            continue
        if remote is not None:
            raise RuntimeError("REMOTE_UNCERTAIN_STOP")
        if row_state == "RUNNING":
            # Ambiguous remote effects are never blindly retried.
            raise RuntimeError("RUNNING_WITHOUT_REMOTE_EVIDENCE_REQUIRES_REVIEW")
        transition(root, item, "RUNNING", "START_AFTER_RESTART")
        external_create(root, item)
        if external_read(root, item) != EXPECTED[item]:
            raise RuntimeError("POSTWRITE_READBACK_FAILED")
        transition(root, item, "DONE_VERIFIED", "VERIFIED_AFTER_RESTART")
        counts["new_simulated_writes"] += 1
    after = state(root)
    if after["job"] != "DONE_VERIFIED" or any(v != "DONE_VERIFIED" for v in after["items"].values()):
        raise RuntimeError("RESUME_INCOMPLETE")
    counts.update({"job_state": after["job"], "done_items": len(after["items"]),
                   "external_effects_before": before,
                   "external_effects_after": count_external(root),
                   "ledger_events": after["events"]})
    return counts


def run_canary():
    with tempfile.TemporaryDirectory(prefix=PREFIX) as directory:
        root = Path(directory)
        register(root)
        script = str(Path(__file__).resolve())
        child = subprocess.run([sys.executable, script, "--crash-child", str(root)],
                               capture_output=True, text=True, timeout=20, check=False)
        if child.returncode != -signal.SIGKILL or "CRASH_AFTER_EXTERNAL_COMMIT_BEFORE_LEDGER_ACK" not in child.stdout:
            raise RuntimeError("SCHEDULED_CRASH_NOT_OBSERVED")
        partial = state(root)
        if partial["items"] != {93001: "DONE_VERIFIED", 93002: "RUNNING", 93003: "PENDING", 93004: "DONE_VERIFIED"}:
            raise RuntimeError("PARTIAL_CHECKPOINT_NOT_PERSISTED")
        if count_external(root) != 3:
            raise RuntimeError("EXTERNAL_PARTIAL_EFFECTS_MISMATCH")
        first = subprocess.run([sys.executable, script, "--resume", str(root)],
                               capture_output=True, text=True, timeout=20, check=False)
        if first.returncode != 0:
            raise RuntimeError("RESUME_FAILED: " + first.stderr[:250])
        outcome = json.loads(first.stdout)
        if (outcome["skipped_verified"] != 2 or outcome["reconciled_uncertain"] != 1
                or outcome["new_simulated_writes"] != 1 or outcome["external_effects_after"] != 4):
            raise RuntimeError("RESUME_COUNTS_INVALID")
        second = subprocess.run([sys.executable, script, "--resume", str(root)],
                                capture_output=True, text=True, timeout=20, check=False)
        if second.returncode != 0:
            raise RuntimeError("REPLAY_FAILED: " + second.stderr[:250])
        replay = json.loads(second.stdout)
        if (replay["skipped_verified"] != 4 or replay["new_simulated_writes"] != 0
                or replay["reconciled_uncertain"] != 0
                or replay["external_effects_after"] != outcome["external_effects_after"]
                or replay["ledger_events"] != outcome["ledger_events"]):
            raise RuntimeError("REPLAY_CAUSED_DUPLICATES")
        return {"stage": "DO_LEDGER_PARTIAL_RESUME_ISOLATED_PASS", "child_exit": child.returncode,
                "partial_states": partial["items"], "first_resume": outcome,
                "replay": replay, "provider_writes": 0, "simulated_backend": True,
                "production_ledger_access": False, "service_restarted": False}


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in ("--crash-child", "--resume"):
        target = Path(sys.argv[2])
        if sys.argv[1] == "--crash-child":
            seed_and_crash(target)
        else:
            print(json.dumps(resume(target), sort_keys=True), flush=True)
    elif len(sys.argv) == 1:
        print(json.dumps(run_canary(), sort_keys=True), flush=True)
    else:
        raise SystemExit("INVALID_MODE")
