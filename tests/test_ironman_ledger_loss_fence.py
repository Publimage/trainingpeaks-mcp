"""Loss of a provisioned ledger must not initialize an empty execution history."""

import sqlite3

import pytest
from test_ironman_authorization import authority, call_flow, control  # noqa: F401
from test_ironman_preview_approval import context, real_flow  # noqa: F401

from scripts.ironman_jobs.ironman_unified_changeset_engine import ChangeStop, Ledger


@pytest.mark.parametrize("loss", ["missing", "empty"])
def test_existing_only_ledger_refuses_lost_history_without_reinitialization(tmp_path, loss):
    path = tmp_path / "ledger.sqlite3"
    Ledger(path).close()  # Explicit host initialization is still supported.
    if loss == "missing":
        path.unlink()
    else:
        path.write_bytes(b"")
    with pytest.raises((PermissionError, ChangeStop)):
        Ledger(path, create=False)
    if loss == "missing":
        assert not path.exists()
    else:
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


def test_existing_ledger_opens_without_erasing_persistent_history(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    ledger = Ledger(path)
    ledger.db.execute("INSERT INTO requests VALUES ('kept','hash','timestamp')")
    ledger.db.commit()
    ledger.close()
    ledger = Ledger(path, create=False)
    assert ledger.db.execute("SELECT * FROM requests").fetchall() == [("kept", "hash", "timestamp")]
    ledger.close()


@pytest.mark.parametrize("loss", ["missing", "empty"])
def test_flow_with_real_approval_refuses_lost_ledger_before_provider_io(request, tmp_path, loss):
    ctx = request.getfixturevalue("context")
    request.getfixturevalue("authority")
    flow = request.getfixturevalue("real_flow")
    from scripts.ironman_jobs.ironman_unified_prefect_flow import compose_operator_runtime
    from tp_mcp.operator_runtime import bind_operator_runtime

    approval = call_flow(flow, ctx, tmp_path, "approve_preview")
    call_flow(flow, ctx, tmp_path, "bind_execution", approval)
    path = tmp_path / "lost-ledger.sqlite3"
    Ledger(path).close()
    if loss == "missing":
        path.unlink()
    else:
        path.write_bytes(b"")

    def no_read(_):
        raise AssertionError("PROVIDER_MUST_NOT_BE_OPENED")

    ctx["provider"].read = no_read
    runtime = compose_operator_runtime(
        ledger_path=str(path),
        authorize_request=lambda _: False,
        writers={"plan.workout.patch": ctx["provider"]},
        enabled_write_kinds=frozenset({"plan.workout.patch"}),
    )
    with (
        bind_operator_runtime(runtime),
        pytest.raises(
            (PermissionError, ChangeStop),
            match="LOCAL_STATE_OPEN_DENIED|LOCAL_STATE_HISTORY_MISSING|LEDGER_RECONCILIATION_REQUIRED",
        ),
    ):
        flow.unified_changeset_flow.fn(
            control(ctx, approval),
            str(path),
            mode="execute_bound",
            requested_targets=ctx["review"]["requested_targets"],
        )
    assert ctx["provider"].writes == 0
    assert not path.exists() if loss == "missing" else path.read_bytes() == b""
