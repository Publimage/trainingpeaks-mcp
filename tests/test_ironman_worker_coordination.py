"""Real processes and SQLite ownership; synthetic provider only."""
import subprocess
import sys
from pathlib import Path
from threading import Event
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    ChangeStop, Ledger, digest, run_changeset,
)


def manifest(request="worker-test-001"):
    return {"schema": "IRONMAN_CHANGESET_V1", "request_id": request,
            "owner_id": 2116886, "reviewed_revision": "a" * 40,
            "approval_scope": "approved:worker-test", "changes": [{
                "id": "patch01", "kind": "plan.workout.patch", "depends_on": [],
                "target": {"provider": "trainingpeaks", "owner_id": 2116886,
                           "container_kind": "training_plan", "container_id": 501, "resource_id": 31},
                "before_sha256": digest({"value": 1}), "after_sha256": digest({"value": 2}),
                "payload": {"desired": {"value": 2}},
            }]}


class BlockingProvider:
    def __init__(self):
        self.entered, self.release = Event(), Event()
        self.value = {"value": 1}
        self.writes = 0

    def read(self, _):
        return dict(self.value)

    def apply(self, _):
        self.writes += 1
        self.entered.set()
        assert self.release.wait(timeout=5)
        self.value = {"value": 2}


def execute(path, provider, request="worker-test-001"):
    ledger = Ledger(path)
    try:
        return run_changeset(manifest(request), {"plan.workout.patch": provider}, ledger,
                             execute=True, reviewed_revision="a" * 40,
                             approval_scope="approved:worker-test", authorize_execution=lambda *_: True)
    finally:
        ledger.close()


@pytest.mark.parametrize("second_request", ["worker-test-001", "worker-test-002"])
def test_two_workers_cannot_enter_writer_on_shared_ledger(tmp_path, second_request):
    path = tmp_path / "ledger.sqlite3"
    provider = BlockingProvider()
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(execute, path, provider)
        try:
            assert provider.entered.wait(timeout=5)
            with pytest.raises(ChangeStop, match="EXECUTION_WORKER_BUSY"):
                execute(path, provider, second_request)
            assert provider.writes == 1
        finally:
            provider.release.set()
        assert first.result(timeout=10)["request_state"] == "WORK_COMPLETE"
    assert execute(path, provider)["request_state"] == "WORK_COMPLETE"
    assert provider.writes == 1


def test_dead_process_keeps_worker_slot_blocked_without_takeover(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    code = '''
import os,sys
from scripts.ironman_jobs.ironman_unified_changeset_engine import Ledger
ledger = Ledger(sys.argv[1])
with ledger.execution_worker("crashed-request"):
    os._exit(0)
'''
    result = subprocess.run([sys.executable, "-c", code, str(path)],
                            cwd=Path(__file__).parents[1], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
    provider = BlockingProvider()
    with pytest.raises(ChangeStop, match="EXECUTION_WORKER_BUSY"):
        execute(path, provider)
    assert provider.writes == 0


def test_regular_exception_releases_only_its_own_worker_slot(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite3")
    try:
        with pytest.raises(RuntimeError):
            with ledger.execution_worker("request-one"):
                raise RuntimeError("before provider call")
        with ledger.execution_worker("request-two"):
            assert ledger.db.execute("SELECT request_id FROM execution_workers").fetchone() == ("request-two",)
        assert ledger.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (0,)
    finally:
        ledger.close()
