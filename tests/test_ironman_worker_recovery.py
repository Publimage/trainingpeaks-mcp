"""Read-only recovery with real child processes, kernel locks and SQLite."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import sqlite3

import pytest

from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    ChangeStop, Ledger, SecurityDenied, recover_execution_worker, run_changeset,
)
from test_ironman_worker_coordination import manifest


CHILD = '''
import json,os,sys
from scripts.ironman_jobs.ironman_unified_changeset_engine import Ledger,validate_manifest
ledger = Ledger(sys.argv[1])
m = json.loads(sys.argv[2])
with ledger.execution_worker(m["request_id"]):
    state = sys.argv[3]
    if state != "before-setup":
        ledger.setup(m,validate_manifest(m),migrate_schema=True)
        ledger.set_state(m["request_id"],m["changes"][0]["id"],state)
        if state in {"RUNNING","UNKNOWN_NEEDS_READBACK"}:
            ledger.claim(m["request_id"],m["changes"][0])
    owner = ledger.db.execute("SELECT owner FROM execution_workers").fetchone()[0]
    print(owner,flush=True)
    if sys.argv[4] == "active":
        input()
    else:
        os._exit(0)
'''


def orphan(path, m=None, state="RUNNING"):
    result = subprocess.run([sys.executable, "-c", CHILD, str(path), json.dumps(m or manifest()), state, "crash"],
                            cwd=Path(__file__).parents[1], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
    return result.stdout.decode().strip()


class Reader:
    def __init__(self, value=None, fail=False):
        self.value = value if value is not None else {"value": 2}
        self.fail, self.reads, self.writes = fail, 0, 0

    def read(self, _):
        self.reads += 1
        if self.fail:
            raise ConnectionError("synthetic unavailable")
        return dict(self.value)

    def apply(self, _):
        self.writes += 1
        raise AssertionError("RECOVERY_MUST_NEVER_WRITE")


def recover(ledger, owner, reader, m=None, authority=lambda *_: True):
    return recover_execution_worker(m or manifest(), {"plan.workout.patch": reader}, ledger,
                                    expected_owner=owner, authorize_recovery=authority)


def test_backup_preserves_uncertain_claim_but_cannot_attest_original_worker_quiescence(tmp_path):
    from scripts.ironman_jobs.ironman_local_state import connect_private_sqlite

    source = tmp_path / "original.sqlite3"
    owner = orphan(source)
    ledger = Ledger(source)
    copy = tmp_path / "restore.sqlite3"
    db, _ = connect_private_sqlite(copy)
    try:
        ledger.db.backup(db)
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert list(db.iterdump()) == list(ledger.db.iterdump())
    finally:
        db.close()
        ledger.close()
    restored, reader = Ledger(copy), Reader()
    try:
        assert restored.status(manifest()["request_id"], "patch01") == "RUNNING"
        assert restored.db.execute("SELECT count(*) FROM resource_claims").fetchone() == (1,)
        with pytest.raises(ChangeStop, match="WORKER_QUIESCENCE_UNVERIFIABLE"):
            recover(restored, owner, reader)
        assert reader.reads == reader.writes == 0
        assert restored.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (1,)
        assert restored.db.execute("SELECT count(*) FROM resource_claims").fetchone() == (1,)
    finally:
        restored.close()


def test_orphaned_verified_write_is_reconciled_and_never_replayed(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    owner = orphan(path)
    ledger, reader = Ledger(path), Reader()
    try:
        result = recover(ledger, owner, reader)
        assert result["state"] == "WORKER_RECOVERED"
        assert result["provider_writes"] == 0 and reader.writes == 0
        assert ledger.status(manifest()["request_id"], "patch01") == "DONE_VERIFIED"
        assert ledger.db.execute("SELECT count(*) FROM resource_claims").fetchone() == (0,)
        reads = reader.reads
        assert recover(ledger, owner, reader)["reused"] is True
        assert reader.reads == reads
        resumed = run_changeset(manifest(), {"plan.workout.patch": reader}, ledger,
                                execute=True, reviewed_revision="a" * 40,
                                approval_scope="approved:worker-test", authorize_execution=lambda *_: True)
        assert resumed["request_state"] == "WORK_COMPLETE" and reader.writes == 0
    finally:
        ledger.close()


@pytest.mark.parametrize("read_failed", [False, True])
def test_uncertain_write_keeps_resource_claim_and_is_not_retried(tmp_path, read_failed):
    path = tmp_path / "ledger.sqlite3"
    owner = orphan(path)
    ledger, reader = Ledger(path), Reader({"value": 1}, fail=read_failed)
    try:
        result = recover(ledger, owner, reader)
        assert result["reconciliation_required"] is True
        assert ledger.status(manifest()["request_id"], "patch01") == "UNKNOWN_NEEDS_READBACK"
        assert ledger.db.execute("SELECT count(*) FROM resource_claims").fetchone() == (1,)
        assert ledger.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (0,)
        resumed = run_changeset(manifest(), {"plan.workout.patch": reader}, ledger,
                                execute=True, reviewed_revision="a" * 40,
                                approval_scope="approved:worker-test", authorize_execution=lambda *_: True)
        assert resumed["request_state"] == "ACTION_INCOMPLETE" and reader.writes == 0
    finally:
        ledger.close()


def test_live_worker_cannot_be_recovered_even_with_correct_owner(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    process = subprocess.Popen([sys.executable, "-c", CHILD, str(path), json.dumps(manifest()), "RUNNING", "active"],
                               cwd=Path(__file__).parents[1], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ledger = None
    try:
        owner = process.stdout.readline().strip()
        assert owner
        ledger, reader = Ledger(path), Reader()
        with pytest.raises(ChangeStop, match="EXECUTION_WORKER_BUSY"):
            recover(ledger, owner, reader)
        assert reader.reads == 0 and reader.writes == 0
        assert ledger.db.execute("SELECT owner FROM execution_workers").fetchone() == (owner,)
    finally:
        if ledger:
            ledger.close()
        process.communicate("\n", timeout=10)
        assert process.returncode == 0


@pytest.mark.parametrize("failure", ["legacy", "wrong-owner", "different-manifest", "replaced-lock"])
def test_unverifiable_recovery_cannot_clear_slot(tmp_path, failure):
    path = tmp_path / "ledger.sqlite3"
    owner = orphan(path)
    ledger, reader, m = Ledger(path), Reader(), manifest()
    try:
        if failure == "legacy":
            ledger.db.execute("DELETE FROM execution_worker_protocol")
            ledger.db.commit()
        elif failure == "wrong-owner":
            owner = "f" * 32
        elif failure == "different-manifest":
            m = copy.deepcopy(m)
            m["changes"][0]["after_sha256"] = "f" * 64
        else:
            replacement = tmp_path / "replacement"
            replacement.write_text("")
            replacement.chmod(0o600)
            replacement.replace(tmp_path / "ledger.sqlite3.worker.lock")
        with pytest.raises(ChangeStop):
            recover(ledger, owner, reader, m=m)
        assert reader.reads == 0 and reader.writes == 0
        assert ledger.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (1,)
    finally:
        ledger.close()


@pytest.mark.parametrize("when", ["before", "after-read"])
def test_current_authorization_required_before_and_after_readback(tmp_path, when):
    path = tmp_path / "ledger.sqlite3"
    owner = orphan(path)
    ledger, reader, calls = Ledger(path), Reader(), []

    def authority(*_):
        calls.append(True)
        return when != "before" and len(calls) == 1

    try:
        with pytest.raises(SecurityDenied):
            recover(ledger, owner, reader, authority=authority)
        assert ledger.status(manifest()["request_id"], "patch01") == "RUNNING"
        assert ledger.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (1,)
        assert reader.writes == 0
    finally:
        ledger.close()


def test_crash_before_request_registration_can_be_cleared_without_provider(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    owner = orphan(path, state="before-setup")
    ledger, reader = Ledger(path), Reader()
    try:
        result = recover(ledger, owner, reader)
        assert result["results"] == []
        assert ledger.db.execute("SELECT count(*) FROM requests").fetchone() == (0,)
        assert reader.reads == reader.writes == 0
    finally:
        ledger.close()


def test_recovery_preserves_security_denial(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    owner = orphan(path, state="BLOCKED_SECURITY")
    ledger, reader = Ledger(path), Reader()
    try:
        recover(ledger, owner, reader)
        assert ledger.status(manifest()["request_id"], "patch01") == "BLOCKED_SECURITY"
        assert reader.reads == reader.writes == 0
    finally:
        ledger.close()


def test_recovery_receipt_tampering_is_refused(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    owner = orphan(path)
    ledger, reader = Ledger(path), Reader()
    try:
        recover(ledger, owner, reader)
        ledger.db.execute("UPDATE worker_recoveries SET receipt='{}'")
        ledger.db.commit()
        with pytest.raises(ChangeStop, match="RECOVERY_RECEIPT_CORRUPT"):
            recover(ledger, owner, reader)
    finally:
        ledger.close()


def test_recovery_transaction_failure_preserves_slot_claims_and_state(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    owner = orphan(path)
    ledger, reader = Ledger(path), Reader()
    try:
        ledger.db.execute("""CREATE TRIGGER fail_recovery BEFORE INSERT ON worker_recoveries
            BEGIN SELECT RAISE(ABORT,'synthetic failure'); END""")
        ledger.db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            recover(ledger, owner, reader)
        assert ledger.status(manifest()["request_id"], "patch01") == "RUNNING"
        assert ledger.db.execute("SELECT count(*) FROM resource_claims").fetchone() == (1,)
        assert ledger.db.execute("SELECT owner FROM execution_workers").fetchone() == (owner,)
        assert ledger.db.execute("SELECT count(*) FROM worker_recoveries").fetchone() == (0,)
    finally:
        ledger.close()


def test_state_changed_outside_worker_protocol_refuses_recovery(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    owner = orphan(path)
    ledger, reader = Ledger(path), Reader()
    original_read = reader.read

    def read_and_external_change(spec):
        result = original_read(spec)
        # Simulate an incompatible maintenance/old worker modifying the DB.
        ledger.db.execute("UPDATE change_events SET reason='external state change'")
        ledger.db.commit()
        return result

    reader.read = read_and_external_change
    try:
        with pytest.raises(ChangeStop, match="RECOVERY_STATE_CHANGED"):
            recover(ledger, owner, reader)
        assert ledger.db.execute("SELECT owner FROM execution_workers").fetchone() == (owner,)
        assert ledger.db.execute("SELECT count(*) FROM worker_recoveries").fetchone() == (0,)
    finally:
        ledger.close()


@pytest.mark.parametrize("prior_state", ["RUNNING", "UNKNOWN_NEEDS_READBACK", "DONE_VERIFIED", "PENDING"])
def test_denial_observed_during_orphan_recovery_is_persisted_and_not_retried(tmp_path, prior_state):
    path = tmp_path / "ledger.sqlite3"
    owner = orphan(path, state=prior_state)
    ledger = Ledger(path)

    class DeniedReader(Reader):
        def read(self, spec):
            self.reads += 1
            raise SecurityDenied("SYNTHETIC_PROVIDER_DENIED")

    reader = DeniedReader()
    try:
        result = recover(ledger, owner, reader)
        assert result["results"][0]["state"] == "BLOCKED_SECURITY"
        assert result["reconciliation_required"] is True
        assert ledger.status(manifest()["request_id"], "patch01") == "BLOCKED_SECURITY"
        expected_claims = int(prior_state in {"RUNNING", "UNKNOWN_NEEDS_READBACK"})
        assert ledger.db.execute("SELECT count(*) FROM resource_claims").fetchone() == (expected_claims,)
        assert recover(ledger, owner, Reader())["reused"] is True
        assert reader.writes == 0
        restored = Reader()
        resumed = run_changeset(manifest(), {"plan.workout.patch": restored}, ledger, execute=True,
                                reviewed_revision="a" * 40, approval_scope="approved:worker-test",
                                authorize_execution=lambda *_: True)
        assert resumed["results"][0]["state"] == "BLOCKED_SECURITY"
        assert restored.reads == restored.writes == 0
    finally:
        ledger.close()
