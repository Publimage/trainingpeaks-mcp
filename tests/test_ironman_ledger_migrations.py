"""Versioned ledger migration: real SQLite, no provider access."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3

import pytest

from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    ChangeStop, Ledger, digest, run_changeset,
)


def seed(ledger):
    rows = [
        ("req-001", "skipped-001", "SKIPPED_DEPENDENCY", "a" * 64, "old-time", "old reason"),
        ("req-001", "denied-001", "BLOCKED_SECURITY", "b" * 64, "old-time", "PROVIDER_DENIAL_NO_RETRY"),
        ("req-001", "unknown-001", "UNKNOWN_NEEDS_READBACK", None, "old-time", "uncertain"),
        ("req-001", "done-001", "DONE_VERIFIED", "c" * 64, "old-time", None),
    ]
    ledger.db.execute("INSERT INTO requests VALUES ('req-001',?,'old-time')", ("d" * 64,))
    ledger.db.executemany("INSERT INTO change_events VALUES (?,?,?,?,?,?)", rows)
    ledger.db.execute("INSERT INTO resource_claims VALUES ('resource-001','req-001','unknown-001')")
    ledger.db.commit()
    return rows


def test_versioned_migration_preserves_evidence_and_denials(tmp_path):
    db = Ledger(tmp_path / "ledger.sqlite3")
    try:
        original = seed(db)
        requests = db.db.execute("SELECT * FROM requests").fetchall()
        claims = db.db.execute("SELECT * FROM resource_claims").fetchall()
        assert db.migrate_schema() == {"version": 1, "reused": False, "migrated_events": 1}
        assert db.db.execute("SELECT * FROM ledger_event_migration_backup").fetchall() == [original[0]]
        changed = db.db.execute("SELECT * FROM change_events WHERE change_id='skipped-001'").fetchone()
        assert changed == (*original[0][:2], "PENDING", *original[0][3:])
        for row in original[1:]:
            assert db.db.execute("SELECT * FROM change_events WHERE change_id=?", (row[1],)).fetchone() == row
        assert db.db.execute("SELECT * FROM requests").fetchall() == requests
        assert db.db.execute("SELECT * FROM resource_claims").fetchall() == claims
        assert db.migrate_schema() == {"version": 1, "reused": True, "migrated_events": 0}
        with pytest.raises(ChangeStop, match="LEDGER_INVALID_STATE"):
            db.set_state("req-001", "skipped-001", "SKIPPED_DEPENDENCY")
    finally:
        db.close()
    reopened = Ledger(tmp_path / "ledger.sqlite3")
    try:
        assert reopened.migrate_schema()["reused"] is True
        assert reopened.status("req-001", "denied-001") == "BLOCKED_SECURITY"
    finally:
        reopened.close()


def test_migration_rolls_back_all_ddl_and_events_on_failure(tmp_path):
    db = Ledger(tmp_path / "ledger.sqlite3")
    try:
        original = seed(db)
        # Simulate an incomplete/unrecognized import, not a valid schema.
        db.db.execute("CREATE TABLE ledger_event_migration_backup (invalid TEXT)")
        db.db.commit()
        with pytest.raises(sqlite3.OperationalError):
            db.migrate_schema()
        assert db.db.execute("SELECT * FROM change_events ORDER BY rowid").fetchall() == original
        assert db.db.execute("SELECT name FROM sqlite_master WHERE name='ledger_migrations'").fetchone() is None
        assert not db.db.in_transaction
        db.db.execute("DROP TABLE ledger_event_migration_backup")
        db.db.commit()
        assert db.migrate_schema()["migrated_events"] == 1
    finally:
        db.close()


def test_concurrent_connections_apply_migration_once(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    initial = Ledger(path)
    seed(initial)
    initial.close()
    barrier = Barrier(2)

    def worker():
        db = Ledger(path)
        try:
            barrier.wait(timeout=5)
            return db.migrate_schema()
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert sorted(row["reused"] for row in results) == [False, True]
    assert sum(row["migrated_events"] for row in results) == 1


def request():
    return {"schema": "IRONMAN_CHANGESET_V1", "request_id": "fresh-request",
            "owner_id": 2116886, "reviewed_revision": "a" * 40,
            "approval_scope": "approved:migration-test", "changes": [{
                "id": "patch01", "kind": "plan.note.patch", "depends_on": [],
                "target": {"provider": "trainingpeaks", "owner_id": 2116886,
                           "container_kind": "training_plan", "container_id": 501, "resource_id": 31},
                "before_sha256": digest({"v": 1}), "after_sha256": digest({"v": 2}),
                "payload": {"desired": {"v": 2}},
            }]}


def test_preview_and_denied_execution_never_migrate(tmp_path):
    db = Ledger(tmp_path / "ledger.sqlite3")
    try:
        original = seed(db)
        m = request()
        run_changeset(m, {}, db, execute=False)
        with pytest.raises(ChangeStop, match="EXECUTION_AUTHORITY_REQUIRED"):
            run_changeset(m, {}, db, execute=True, reviewed_revision=m["reviewed_revision"],
                          approval_scope=m["approval_scope"])
        assert db.db.execute("SELECT * FROM change_events WHERE request_id='req-001' ORDER BY rowid").fetchall() == original
        assert db.db.execute("SELECT name FROM sqlite_master WHERE name='ledger_migrations'").fetchone() is None
    finally:
        db.close()


@pytest.mark.parametrize("future", [False, True])
def test_unknown_schema_or_reintroduced_legacy_state_blocks_execution(tmp_path, future):
    db = Ledger(tmp_path / "ledger.sqlite3")
    try:
        seed(db)
        db.migrate_schema()
        if future:
            db.db.execute("INSERT INTO ledger_migrations VALUES (2,'future')")
            code = "LEDGER_SCHEMA_UNSUPPORTED"
        else:
            db.db.execute("UPDATE change_events SET state='SKIPPED_DEPENDENCY' WHERE change_id='skipped-001'")
            code = "LEDGER_LEGACY_ROWS_AFTER_MIGRATION"
        db.db.commit()
        m = request()
        with pytest.raises(ChangeStop, match=code):
            run_changeset(m, {}, db, execute=True, reviewed_revision=m["reviewed_revision"],
                          approval_scope=m["approval_scope"], authorize_execution=lambda *_: True)
        assert db.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (0,)
    finally:
        db.close()


def test_manifest_drift_does_not_migrate_other_requests(tmp_path):
    db = Ledger(tmp_path / "ledger.sqlite3")
    try:
        original = seed(db)
        m = request()
        m["request_id"] = "req-001"  # Already bound to a different manifest.
        with pytest.raises(ChangeStop, match="IDEMPOTENCY_MANIFEST_DRIFT"):
            run_changeset(m, {}, db, execute=True, reviewed_revision=m["reviewed_revision"],
                          approval_scope=m["approval_scope"], authorize_execution=lambda *_: True)
        assert db.db.execute("SELECT * FROM change_events ORDER BY rowid").fetchall() == original
        assert db.db.execute("SELECT name FROM sqlite_master WHERE name='ledger_migrations'").fetchone() is None
    finally:
        db.close()


def test_failed_migration_does_not_register_new_request_or_leave_worker_owned(tmp_path):
    db = Ledger(tmp_path / "ledger.sqlite3")
    try:
        original = seed(db)
        db.db.execute("CREATE TABLE ledger_event_migration_backup (invalid TEXT)")
        db.db.commit()
        m = request()
        with pytest.raises(sqlite3.OperationalError):
            run_changeset(m, {}, db, execute=True, reviewed_revision=m["reviewed_revision"],
                          approval_scope=m["approval_scope"], authorize_execution=lambda *_: True)
        assert db.db.execute("SELECT 1 FROM requests WHERE request_id=?", (m["request_id"],)).fetchone() is None
        assert db.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (0,)
        assert db.db.execute("SELECT * FROM change_events ORDER BY rowid").fetchall() == original
    finally:
        db.close()


@pytest.mark.parametrize("already_versioned", [False, True])
def test_unknown_event_state_is_not_silently_converted(tmp_path, already_versioned):
    db = Ledger(tmp_path / "ledger.sqlite3")
    try:
        seed(db)
        if already_versioned:
            db.migrate_schema()
        db.db.execute("UPDATE change_events SET state='FUTURE_UNKNOWN' WHERE change_id='unknown-001'")
        db.db.commit()
        original = db.db.execute("SELECT * FROM change_events ORDER BY rowid").fetchall()
        with pytest.raises(ChangeStop, match="LEDGER_UNKNOWN_STATE"):
            db.migrate_schema()
        assert db.db.execute("SELECT * FROM change_events ORDER BY rowid").fetchall() == original
        assert not db.db.in_transaction
    finally:
        db.close()
