"""Synthetic local SQLite files only; no provider, production state or network."""
import os
from pathlib import Path

import pytest

from scripts.ironman_jobs.ironman_dynamic_request_store import DraftStore
from scripts.ironman_jobs.ironman_unified_changeset_engine import ChangeStop, Ledger, run_changeset
from test_ironman_worker_coordination import manifest


@pytest.mark.parametrize("store_type", [DraftStore, Ledger])
def test_local_store_rejects_hardlink_alias_before_sqlite(store_type, tmp_path):
    path, alias = tmp_path / "state.sqlite3", tmp_path / "alias.sqlite3"
    store = store_type(path)
    store.close()
    os.link(path, alias)
    before = path.read_bytes()
    with pytest.raises(PermissionError):
        store_type(alias)
    assert path.read_bytes() == before
    assert not Path(str(alias) + "-wal").exists()


@pytest.mark.parametrize("store_type", [DraftStore, Ledger])
def test_local_store_is_created_private_under_permissive_umask(store_type, tmp_path):
    path = tmp_path / "state.sqlite3"
    previous = os.umask(0)
    try:
        store = store_type(path)
        try:
            assert path.stat().st_mode & 0o777 == 0o600
        finally:
            store.close()
    finally:
        os.umask(previous)


def test_in_memory_ledger_cannot_enter_provider_execution():
    ledger = Ledger(":memory:")
    class NoProviderIO:
        def read(self, _):
            raise AssertionError("VOLATILE_EXECUTION_MUST_NOT_READ")
        def apply(self, _):
            raise AssertionError("VOLATILE_EXECUTION_MUST_NOT_WRITE")
    try:
        with pytest.raises(ChangeStop, match="EXECUTION_REQUIRES_PERSISTENT_LEDGER"):
            run_changeset(manifest(), {"plan.workout.patch": NoProviderIO()}, ledger,
                          execute=True, reviewed_revision="a" * 40, approval_scope="approved:worker-test",
                          authorize_execution=lambda *_: True)
        assert ledger.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (0,)
    finally:
        ledger.close()


@pytest.mark.parametrize("store_type", [DraftStore, Ledger])
@pytest.mark.parametrize("mode", [0o644, 0o666, 0o400])
def test_unsafe_existing_permissions_are_rejected_without_repair(store_type, tmp_path, mode):
    path = tmp_path / "state.sqlite3"
    store = store_type(path)
    store.close()
    original = path.read_bytes()
    path.chmod(mode)
    with pytest.raises(PermissionError):
        store_type(path)
    assert path.read_bytes() == original
    assert path.stat().st_mode & 0o777 == mode


@pytest.mark.parametrize("store_type", [DraftStore, Ledger])
@pytest.mark.parametrize("alias", ["leaf-symlink", "parent-symlink", "sidecar-symlink", "sidecar-hardlink", "fifo"])
def test_unsafe_file_and_sidecar_aliases_are_rejected_before_sqlite(store_type, tmp_path, alias):
    directory = tmp_path / "real"
    directory.mkdir(mode=0o700)
    path = directory / "state.sqlite3"
    destination = path
    if alias == "parent-symlink":
        link = tmp_path / "parent-link"
        link.symlink_to(directory, target_is_directory=True)
        path = link / path.name
    elif alias == "fifo":
        os.mkfifo(path, 0o600)
    else:
        store = store_type(path)
        store.close()
        if alias == "leaf-symlink":
            link = directory / "leaf-link"
            link.symlink_to(path)
            path = link
        else:
            foreign = directory / "unrelated-file"
            foreign.write_bytes(b"synthetic-unrelated-content")
            foreign.chmod(0o600)
            sidecar = Path(str(path) + "-wal")
            if alias == "sidecar-symlink":
                sidecar.symlink_to(foreign)
            else:
                os.link(foreign, sidecar)
    with pytest.raises(PermissionError):
        store_type(path)
    if alias == "parent-symlink":
        assert not destination.exists()
    if alias.startswith("sidecar"):
        assert foreign.read_bytes() == b"synthetic-unrelated-content"


@pytest.mark.parametrize("store_type", [DraftStore, Ledger])
def test_replaced_database_identity_is_rejected_before_state_access(store_type, tmp_path):
    path = tmp_path / "state.sqlite3"
    store = store_type(path)
    saved = path.with_name("saved.sqlite3")
    path.rename(saved)
    path.write_bytes(b"unrelated-replacement")
    path.chmod(0o600)
    try:
        with pytest.raises(PermissionError, match="IDENTITY_CHANGED"):
            store.verify_storage()
        assert path.read_bytes() == b"unrelated-replacement"
        if isinstance(store, Ledger):
            with pytest.raises(PermissionError, match="IDENTITY_CHANGED"):
                with store.execution_worker("synthetic-worker"):
                    raise AssertionError("REPLACED_LEDGER_MUST_NOT_ACQUIRE_WORKER")
        else:
            with pytest.raises(PermissionError, match="IDENTITY_CHANGED"):
                store.get("synthetic-request")
    finally:
        saved.replace(path)
        store.close()


def test_memory_preview_stays_available_without_persistent_state():
    ledger = Ledger(":memory:")
    class Reader:
        def read(self, _):
            return {"value": 1}
        def apply(self, _):
            raise AssertionError("PREVIEW_CANNOT_WRITE")
    try:
        result = run_changeset(manifest(), {"plan.workout.patch": Reader()}, ledger)
        assert result["request_state"] == "PREVIEW_ONLY"
        assert result["results"][0]["state"] == "PREFLIGHT_PASS"
    finally:
        ledger.close()


@pytest.mark.parametrize("store_type", [DraftStore, Ledger])
def test_simultaneous_first_open_uses_same_private_inode(store_type, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "shared.sqlite3"
    ready = Barrier(2)
    def open_store():
        ready.wait(timeout=5)
        store = store_type(path)
        try:
            store.verify_storage()
            return store._state_file.identity
        finally:
            store.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: open_store(), range(2)))
    assert results[0] == results[1] == (path.stat().st_dev, path.stat().st_ino)
    assert path.stat().st_mode & 0o777 == 0o600


def test_invalid_database_closes_connection_without_repair(tmp_path, monkeypatch):
    import sqlite3
    from scripts.ironman_jobs import ironman_local_state as state

    path = tmp_path / "invalid.sqlite3"
    path.write_bytes(b"synthetic-not-a-sqlite-database")
    path.chmod(0o600)
    original_connect = sqlite3.connect
    opened = []
    class Connection:
        def __init__(self, *args, **kwargs):
            self.inner = original_connect(*args, **kwargs)
            self.closed = False
            opened.append(self)
        def execute(self, *args):
            return self.inner.execute(*args)
        def close(self):
            self.closed = True
            self.inner.close()
    monkeypatch.setattr(state.sqlite3, "connect", Connection)
    with pytest.raises(sqlite3.DatabaseError):
        state.connect_private_sqlite(path)
    assert len(opened) == 1 and opened[0].closed
    assert path.read_bytes() == b"synthetic-not-a-sqlite-database"


def test_sqlite_initialization_holds_inode_exclusion(monkeypatch, tmp_path):
    import sqlite3
    from scripts.ironman_jobs import ironman_local_state as state
    from scripts.ironman_jobs.ironman_file_lock import FileLockBusy, locked_descriptor

    path = tmp_path / "serialized.sqlite3"
    original_connect = sqlite3.connect
    def checked_connect(*args, **kwargs):
        competing = os.open(path, os.O_RDWR)
        try:
            with pytest.raises(FileLockBusy):
                with locked_descriptor(competing):
                    raise AssertionError("SQLITE_INITIALIZATION_MUST_BE_EXCLUSIVE")
        finally:
            os.close(competing)
        return original_connect(*args, **kwargs)
    monkeypatch.setattr(state.sqlite3, "connect", checked_connect)
    connection, identity = state.connect_private_sqlite(path)
    try:
        identity.verify()
    finally:
        connection.close()


def test_bounded_descriptor_wait_never_clears_active_owner(tmp_path):
    from scripts.ironman_jobs.ironman_file_lock import FileLockBusy, locked_descriptor

    path = tmp_path / "descriptor.lock"
    first = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    second = os.open(path, os.O_RDWR)
    try:
        with locked_descriptor(first):
            with pytest.raises(FileLockBusy):
                with locked_descriptor(second, timeout=0.02):
                    raise AssertionError("WAIT_MUST_NOT_TAKE_OVER")
            with pytest.raises(FileLockBusy):
                with locked_descriptor(second):
                    raise AssertionError("ACTIVE_OWNER_MUST_STILL_HOLD_LOCK")
        with locked_descriptor(second):
            pass
    finally:
        os.close(second)
        os.close(first)


def test_storage_replacement_during_preflight_blocks_write_and_retains_worker(tmp_path):
    path, saved = tmp_path / "state.sqlite3", tmp_path / "saved.sqlite3"
    ledger = Ledger(path)
    writes = []
    class ReplacingReader:
        def read(self, _):
            path.rename(saved)
            path.write_bytes(b"unrelated-replacement")
            path.chmod(0o600)
            return {"value": 1}
        def apply(self, _):
            writes.append(True)
    try:
        with pytest.raises(PermissionError, match="IDENTITY_CHANGED"):
            run_changeset(manifest(), {"plan.workout.patch": ReplacingReader()}, ledger,
                          execute=True, reviewed_revision="a" * 40, approval_scope="approved:worker-test",
                          authorize_execution=lambda *_: True)
        assert writes == [] and path.read_bytes() == b"unrelated-replacement"
        saved.replace(path)
        assert ledger.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (1,)
        assert ledger.db.execute("SELECT count(*) FROM resource_claims").fetchone() == (0,)
    finally:
        if saved.exists():
            saved.replace(path)
        ledger.close()


@pytest.mark.parametrize("store_type", [DraftStore, Ledger])
def test_new_hardlink_after_open_invalidates_store(store_type, tmp_path):
    path, alias = tmp_path / "state.sqlite3", tmp_path / "alias.sqlite3"
    store = store_type(path)
    os.link(path, alias)
    try:
        with pytest.raises(PermissionError, match="FILE_UNSAFE"):
            store.verify_storage()
    finally:
        alias.unlink()
        store.close()
