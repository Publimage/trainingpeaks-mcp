"""Fixed lab acceptance, entirely offline with a simulated provider."""
import copy
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.ironman_jobs import complete_plan_transfer_lab as lab
from tp_mcp.tools.plan_transfer_core import PlanSnapshot, TransferError, TransferItem

OUTSIDE = "d" * 64
SOURCE = "a" * 64
REAL_OUTSIDE_DIGEST = lab._outside_digest


class SimulatedProcessKill(BaseException):
    pass


def _snapshot():
    items = [TransferItem("classic", f"c{i}", i % 56, i // 56, {"title": f"Private workout {i}"})
             for i in range(58)]
    items += [TransferItem("strength", f"s{i}", i * 3, 2, {"title": f"Private gym {i}"}) for i in range(16)]
    items += [TransferItem("note", f"n{i}", i * 6, 3, {"title": f"Private note {i}"}) for i in range(9)]
    items.append(TransferItem("attachment", "n0/a1", 0, 0, {"fileName": "guide.pdf", "sha256": "f" * 64}, "n0"))
    return PlanSnapshot(lab.SOURCE_PLAN_ID, "WINTER offline fixture", "2027-01-04", 56, SOURCE, items)


@pytest.fixture
def memory(monkeypatch, tmp_path):
    state = SimpleNamespace(snapshot=_snapshot(), name=lab.ATHLETE_NAME, rows=[], calls=[], requests=[], mode=None,
                            receipt_existed_before_write=False, source_preserved=True)

    def initialize(self, *_args, **_kwargs):
        self.athlete_name = ""
        self.create_attempts = 0

    async def enter(self):
        return self

    async def leave(self, *_):
        return False

    async def preflight(self, request):
        state.requests.append(request)
        self.athlete_name = state.name
        return copy.deepcopy(state.snapshot)

    async def inventory(self, request):
        return copy.deepcopy(state.rows)

    async def create(self, request, item, target_date, hidden, parent_target_id):
        state.calls.append(item.source_id)
        state.receipt_existed_before_write = lab._read_receipt() is not None
        if state.mode == "timeout":
            raise TimeoutError("commit outcome unknown")
        row = {"id": str(10000 + len(state.calls)), "kind": item.kind, "date": target_date,
               "hidden": hidden, "order": item.order, "content": copy.deepcopy(item.content)}
        if parent_target_id is not None:
            row["parent_id"] = parent_target_id
        state.rows.append(row)
        if state.mode == "kill":
            state.mode = None
            raise SimulatedProcessKill()
        return row["id"]

    async def read_item(self, request, item, target_id, parent_target_id):
        return copy.deepcopy(next(r for r in state.rows if r["kind"] == item.kind and r["id"] == target_id))

    async def verify_source(self, snapshot):
        return state.source_preserved

    for name, method in {"__init__": initialize, "__aenter__": enter, "__aexit__": leave,
                         "preflight": preflight, "inventory": inventory, "create": create,
                         "read_item": read_item, "verify_source": verify_source}.items():
        monkeypatch.setattr(lab.TrainingPeaksTransferGateway, name, method)
    monkeypatch.setattr(lab, "_state_directory", lambda: tmp_path / "state")
    monkeypatch.setattr(lab, "_outside_digest", AsyncMock(return_value=OUTSIDE))
    return state


@pytest.mark.asyncio
async def test_preview_is_read_only_fixed_scope_and_has_no_receipt(memory, capsys):
    result = await lab.run_preview()
    assert result["status"] == "PREVIEW" and result["counts"] == lab.COUNTS
    assert result["create_attempts"] == 0 and memory.calls == [] and lab._read_receipt() is None
    assert all(request.athlete_id == lab.ATHLETE_ID for request in memory.requests)
    printed = capsys.readouterr().out
    assert "Private workout" not in printed and "Private note" not in printed


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("athlete_id", 1234), ("source_plan_id", 1234),
                                         ("start_date", "2028-01-04"), ("request_id", "different"),
                                         ("visible_through", None)])
async def test_lab_rejects_any_changed_target_before_provider_read(memory, field, value):
    async with lab.LabGateway() as gateway:
        with pytest.raises(TransferError) as error:
            await gateway.preflight(replace(lab._request(), **{field: value}))
    assert error.value.code == "LAB_SCOPE_MISMATCH" and memory.requests == [] and memory.calls == []


@pytest.mark.asyncio
async def test_athlete_name_guard_runs_before_mutation(memory):
    memory.name = "Another athlete"
    with pytest.raises(TransferError) as error:
        await lab.run_execute()
    assert error.value.code == "LAB_ATHLETE_NAME_MISMATCH" and memory.calls == []
    assert lab._read_receipt() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["counts", "span"])
async def test_source_shape_guard_runs_before_mutation(memory, change):
    memory.snapshot = (replace(memory.snapshot, items=memory.snapshot.items[:-1]) if change == "counts"
                       else replace(memory.snapshot, day_count=55))
    with pytest.raises(TransferError) as error:
        await lab.run_execute()
    assert error.value.code == "LAB_SOURCE_SHAPE_MISMATCH" and memory.calls == []


@pytest.mark.asyncio
async def test_full_copy_then_read_only_replay_acceptance(memory):
    result = await lab.run_execute()
    assert result["status"] == "DONE_VERIFIED" and result["counts"] == lab.COUNTS
    assert len(memory.calls) == 84 and result["outside_verified"] and result["source_verified"]
    assert memory.receipt_existed_before_write
    receipt = lab._read_receipt()
    assert receipt["source_digest"] == SOURCE and len(receipt["result"]["created_ids"]) == 84
    assert lab._receipt_path().parent.name == "lab-acceptance"
    assert lab._receipt_path().stat().st_mode & 0o777 == 0o600
    replay = await lab.run_verify()
    assert replay["status"] == "DONE_VERIFIED" and replay["create_attempts"] == 0
    assert replay["create_calls_this_run"] == 0 and len(memory.calls) == 84
    assert replay["created_ids"] == result["created_ids"]
    assert any(row["hidden"] for row in memory.rows) and any(not row["hidden"] for row in memory.rows)


@pytest.mark.asyncio
async def test_first_execution_refuses_preexisting_calendar(memory):
    memory.rows = [{"id": "7", "kind": "classic", "date": lab.START_DATE, "hidden": False,
                    "order": 0, "content": {"title": "Existing"}}]
    with pytest.raises(TransferError) as error:
        await lab.run_execute()
    assert error.value.code == "LAB_TARGET_OCCUPIED" and memory.calls == [] and lab._read_receipt() is None


@pytest.mark.asyncio
async def test_timeout_reuses_request_and_does_not_repeat_uncertain_create(memory):
    memory.mode = "timeout"
    first = await lab.run_execute()
    assert first["status"] == "UNCERTAIN" and len(memory.calls) == 1
    memory.mode = None
    again = await lab.run_execute()
    assert again["status"] == "UNCERTAIN" and len(memory.calls) == 1
    assert {request.request_id for request in memory.requests} == {lab.REQUEST_ID}
    with pytest.raises(TransferError) as error:
        await lab.run_verify()
    assert error.value.code == "LAB_COMPLETED_RECEIPT_REQUIRED"


@pytest.mark.asyncio
async def test_process_kill_preserves_receipt_and_resumes_same_copy(memory):
    memory.mode = "kill"
    with pytest.raises(SimulatedProcessKill):
        await lab.run_execute()
    assert lab._read_receipt()["status"] == "PREPARED" and len(memory.rows) == 1
    result = await lab.run_execute()
    assert result["status"] == "DONE_VERIFIED" and len(memory.calls) == 84
    assert len(memory.rows) == 84 and len(set(memory.calls)) == 84


@pytest.mark.asyncio
async def test_outside_drift_after_copy_is_not_reported_as_acceptance(memory, monkeypatch):
    monkeypatch.setattr(lab, "_outside_digest", AsyncMock(side_effect=[OUTSIDE, "e" * 64]))
    result = await lab.run_execute()
    assert result["status"] == "BLOCKED" and result["error_code"] == "LAB_OUTSIDE_DRIFT"
    assert result["source_verified"] is True and result["outside_verified"] is False
    assert len(result["created_ids"]) == 84 and lab._read_receipt()["status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_outside_read_failure_keeps_created_ids_and_no_private_error(memory, monkeypatch, capsys):
    monkeypatch.setattr(lab, "_outside_digest", AsyncMock(side_effect=[OUTSIDE, RuntimeError("secret-body")]))
    result = await lab.run_execute()
    assert result["error_code"] == "LAB_OUTSIDE_UNVERIFIED" and len(result["created_ids"]) == 84
    assert "secret-body" not in capsys.readouterr().out
    assert lab._read_receipt()["status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_changed_source_digest_cannot_rebind_lab_receipt(memory):
    await lab.run_execute()
    memory.snapshot = replace(memory.snapshot, digest="b" * 64)
    with pytest.raises(TransferError) as error:
        await lab.run_execute()
    assert error.value.code == "LAB_SOURCE_CHANGED" and len(memory.calls) == 84


@pytest.mark.asyncio
async def test_verify_subclass_blocks_all_provider_creates_even_if_local_journal_lost(memory):
    await lab.run_execute()
    for path in lab._state_directory().glob("*.json"):
        path.unlink()
    memory.rows.clear()
    with pytest.raises(TransferError) as error:
        await lab.run_verify()
    assert error.value.code == "LAB_REPLAY_FAILED" and len(memory.calls) == 84


@pytest.mark.asyncio
async def test_outside_fingerprint_reads_native_detail_and_detects_changed_blocks():
    class Reader:
        def __init__(self):
            self.reps = 5
            self.routes = []

        async def _get(self, path, shape):
            self.routes.append(("GET", path))
            return []

        async def _native(self, method, path):
            assert method == "GET"
            self.routes.append((method, path))
            if "/calendar/" in path:
                return [{"id": 77}] if "/2027-12-27/" in path else []
            return {"id": 77, "calendarId": lab.ATHLETE_ID, "prescribedDate": "2027-12-28",
                    "blocks": [{"reps": self.reps}]}

    reader = Reader()
    first = await REAL_OUTSIDE_DIGEST(reader)
    reader.reps = 6
    second = await REAL_OUTSIDE_DIGEST(reader)
    assert first != second
    assert ("GET", "/rx/activity/v1/workouts/77") in reader.routes
    assert any("/2028-02-28/2028-03-06" in path for _, path in reader.routes)


@pytest.mark.parametrize("stage", ["preview", "execute", "verify"])
def test_operator_entrypoints_import_and_reject_arbitrary_cli_inputs(stage):
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "ironman_jobs" / f"complete_plan_transfer_lab_{stage}.py"
    result = subprocess.run([sys.executable, str(script), "--not-allowed"], cwd=root,
                            env={**os.environ, "PYTHONPATH": str(root / "src")},
                            capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 2
    output = json.loads(result.stdout)
    assert output["error_code"] == "LAB_ARGUMENTS_NOT_ALLOWED"
