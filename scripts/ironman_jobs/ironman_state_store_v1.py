"""IRONMAN operational ledger v1: SQLite persistence, not a coaching source of truth.

The ledger records only execution checkpoints and provider evidence, and never
supersedes the canonical Drive Decision Log/Product Spec. No scheduling or
TrainingPeaks mutation is implemented here.
"""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/home/ironman/.local/state/ironman-operator/workflows_v1.sqlite3")
SCHEMA_VERSION = 1
STATES = {"PENDING", "RUNNING", "DONE_VERIFIED", "BLOCKED_EXTERNAL", "FAILED_REVIEW", "SKIPPED_DEPENDENCY"}
DDL = (
    """CREATE TABLE IF NOT EXISTS jobs (
      job_id TEXT PRIMARY KEY,
      source_ref TEXT NOT NULL,
      target_provider TEXT NOT NULL,
      target_plan INTEGER NOT NULL,
      expected_items INTEGER NOT NULL CHECK(expected_items > 0),
      state TEXT NOT NULL CHECK(state IN ('PENDING','RUNNING','DONE_VERIFIED','BLOCKED_EXTERNAL','FAILED_REVIEW','SKIPPED_DEPENDENCY')),
      verified_at TEXT NOT NULL,
      evidence_digest TEXT NOT NULL,
      schema_version INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS items (
      job_id TEXT NOT NULL REFERENCES jobs(job_id),
      item_id INTEGER NOT NULL,
      relative_week INTEGER NOT NULL,
      duration_min INTEGER NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('PENDING','RUNNING','DONE_VERIFIED','BLOCKED_EXTERNAL','FAILED_REVIEW','SKIPPED_DEPENDENCY')),
      provider_evidence_sha256 TEXT NOT NULL,
      verified_at TEXT NOT NULL,
      PRIMARY KEY(job_id,item_id)
    )""",
    """CREATE TABLE IF NOT EXISTS events (
      seq INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      at_utc TEXT NOT NULL,
      details_sha256 TEXT NOT NULL
    )"""
)

def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def digest(obj):
    return hashlib.sha256(canon(obj).encode("utf-8")).hexdigest()

def connect(path=DB_PATH, *, read_only=False):
    path = Path(path)
    if read_only:
        if not path.is_file():
            raise RuntimeError("LEDGER_NOT_INITIALIZED")
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    else:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path == DB_PATH:
            os.chmod(path.parent, 0o700)
        db = sqlite3.connect(path, timeout=10)
        os.chmod(path, 0o600)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    if not read_only:
        db.execute("PRAGMA journal_mode=WAL")
        for sql in DDL: db.execute(sql)
        db.commit()
    return db

def record_verified_snapshot(db, job_id, source_ref, target_provider, plan_id, rows):
    """Atomic, idempotent *single snapshot*. Conflicts must stop, never overwrite."""
    if not rows or len({int(r["item_id"]) for r in rows}) != len(rows):
        raise RuntimeError("BAD_OR_DUPLICATE_ITEMS")
    expected = len(rows)
    evidence = digest(sorted(rows,key=lambda r:r["item_id"]))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    params = (job_id, source_ref, target_provider, int(plan_id), expected,
              "DONE_VERIFIED", evidence, SCHEMA_VERSION)
    db.execute("BEGIN IMMEDIATE")
    try:
        prev = db.execute(
          "SELECT job_id,source_ref,target_provider,target_plan,expected_items,state,evidence_digest,schema_version FROM jobs WHERE job_id=?",
          (job_id,)).fetchone()
        if prev:
            assert prev == params, "CONFLICT_EXISTING_JOB_FINGERPRINT"
            old_items = db.execute("SELECT item_id,relative_week,duration_min,state,provider_evidence_sha256 FROM items WHERE job_id=? ORDER BY item_id",(job_id,)).fetchall()
            new_items = sorted((int(r["item_id"]),int(r["relative_week"]),
             int(r["duration_min"]),"DONE_VERIFIED",r["provider_evidence_sha256"]) for r in rows)
            assert old_items == new_items, "CONFLICT_EXISTING_ITEMS"
            db.commit()
            return {"created":False,"job_id":job_id,"items":expected,"digest":evidence}
        db.execute("INSERT INTO jobs(job_id,source_ref,target_provider,target_plan,expected_items,state,verified_at,evidence_digest,schema_version) VALUES(?,?,?,?,?,?,?,?,?)",
                   (job_id,source_ref,target_provider,int(plan_id),expected,"DONE_VERIFIED",now,evidence,SCHEMA_VERSION))
        for r in sorted(rows,key=lambda x:x["item_id"]):
            db.execute("INSERT INTO items(job_id,item_id,relative_week,duration_min,state,provider_evidence_sha256,verified_at) VALUES(?,?,?,?,?,?,?)",
                (job_id,int(r["item_id"]),int(r["relative_week"]),int(r["duration_min"]),"DONE_VERIFIED",r["provider_evidence_sha256"],now))
        db.execute("INSERT INTO events(job_id,kind,at_utc,details_sha256) VALUES(?,?,?,?)",
                   (job_id,"SNAPSHOT_VERIFIED",now,evidence))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"created":True,"job_id":job_id,"items":expected,"digest":evidence}

def read_snapshot(db, job_id):
    w = db.execute("SELECT job_id,source_ref,target_provider,target_plan,expected_items,state,verified_at,evidence_digest,schema_version FROM jobs WHERE job_id=?",(job_id,)).fetchone()
    if not w: raise RuntimeError("JOB_NOT_IN_LEDGER")
    items = db.execute("SELECT item_id,relative_week,duration_min,state,provider_evidence_sha256,verified_at FROM items WHERE job_id=? ORDER BY item_id",(job_id,)).fetchall()
    events = db.execute("SELECT kind,details_sha256 FROM events WHERE job_id=? ORDER BY seq",(job_id,)).fetchall()
    if len(items)!=w[4] or w[5]!="DONE_VERIFIED" or any(x[3]!="DONE_VERIFIED" for x in items):
        raise RuntimeError("LEDGER_INCONSISTENT")
    payload = [{"item_id":x[0],"relative_week":x[1],"duration_min":x[2],"provider_evidence_sha256":x[4]} for x in items]
    if digest(payload)!=w[7] or events!=[("SNAPSHOT_VERIFIED",w[7])]:
        raise RuntimeError("LEDGER_EVIDENCE_CORRUPT")
    return {"job_id":w[0],"source_ref":w[1],"provider":w[2],"plan":w[3],
       "expected_items":w[4],"state":w[5],"verified_at":w[6],
       "evidence_digest":w[7],"schema_version":w[8],
       "items":[{"id":x[0],"week":x[1],"minutes":x[2],"state":x[3]} for x in items],
       "event_count":len(events)}
