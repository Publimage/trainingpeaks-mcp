"""Offline transfer behavior: no credentials, HTTP, or real athlete calendars."""
import copy
import json
from dataclasses import replace

import pytest

from tp_mcp.tools.plan_transfer_core import (
    PlanSnapshot,
    TransferError,
    TransferItem,
    TransferRequest,
    preview,
    transfer,
)

DIGEST = "a" * 64


class ProcessCrash(BaseException):
    pass


class FakeGateway:
    def __init__(self, items=None):
        self.snapshot = PlanSnapshot(100, "Private test plan", "2027-01-04", 14, DIGEST, items or [
            TransferItem("classic", "c1", 0, 0, {"title": "Bike", "duration": 60, "structure": [1, 2]}),
            TransferItem("strength", "s1", 7, 0, {"title": "Gym", "blocks": [{"sets": [3, 4]}]}),
            TransferItem("note", "n1", 0, 1, {"title": "Read first", "description": "Notes"}),
            TransferItem("attachment", "a1", 0, 0, {"name": "guide.pdf", "sha256": "b" * 64}, "n1"),
        ])
        self.rows = []
        self.calls = []
        self.mode = None
        self.source_ok = True
        self.source_change_after = None
        self.bad_inventory = False
        self.inventory_calls = 0
        self.item_reads = 0

    async def preflight(self, request):
        return copy.deepcopy(self.snapshot)

    async def inventory(self, request):
        self.inventory_calls += 1
        if self.bad_inventory:
            raise ConnectionError("inventory unavailable")
        return copy.deepcopy(self.rows)

    async def read_item(self, request, item, target_id, parent_target_id):
        self.item_reads += 1
        if self.bad_inventory:
            raise ConnectionError("readback unavailable")
        return copy.deepcopy(next(r for r in self.rows if r["kind"] == item.kind and r["id"] == target_id))

    async def create(self, request, item, target_date, hidden, parent_target_id):
        self.calls.append(item.source_id)
        if self.mode == "timeout-before":
            raise TimeoutError("unknown commit state")
        row = {"kind": item.kind, "id": f"target-{len(self.calls)}", "date": target_date,
               "order": item.order, "hidden": hidden, "content": copy.deepcopy(item.content)}
        if parent_target_id is not None:
            row["parent_id"] = parent_target_id
        self.rows.append(row)
        if self.mode == "crash":
            self.mode = None
            raise ProcessCrash()
        if self.mode == "timeout-after":
            self.mode = None
            raise TimeoutError("response lost after commit")
        if self.mode == "bad-readback":
            row["content"]["title"] = "Unexpected change"
        if self.mode == "inventory-down":
            self.bad_inventory = True
        return row["id"]

    async def verify_source(self, snapshot):
        if self.source_change_after is not None and len(self.calls) >= self.source_change_after:
            return False
        return self.source_ok


def request(**updates):
    return replace(TransferRequest("copy-test", 100, 200, "2027-02-01", "2027-02-07", DIGEST), **updates)


@pytest.mark.asyncio
async def test_preview_is_read_only_and_does_not_create_journal(tmp_path):
    gateway = FakeGateway()
    result = await transfer(request(expected_source_digest=None), gateway, tmp_path / "private")
    assert result["status"] == "PREVIEW" and result["ready"]
    assert result["counts"] == {"classic": 1, "strength": 1, "note": 1, "attachment": 1}
    assert gateway.calls == [] and not (tmp_path / "private").exists()


@pytest.mark.asyncio
async def test_all_four_kinds_parent_mapping_visibility_and_replay(tmp_path):
    gateway = FakeGateway()
    result = await transfer(request(), gateway, tmp_path, execute=True)
    assert result["status"] == "DONE_VERIFIED"
    assert len(result["created_ids"]) == 4 and result["create_calls_this_run"] == 4
    assert gateway.inventory_calls == 2 and gateway.item_reads == 4
    note = next(row for row in gateway.rows if row["kind"] == "note")
    attachment = next(row for row in gateway.rows if row["kind"] == "attachment")
    assert attachment["parent_id"] == note["id"]
    assert next(row for row in gateway.rows if row["kind"] == "strength")["hidden"]
    assert not note["hidden"] and not attachment["hidden"]
    calls = list(gateway.calls)
    again = await transfer(request(), gateway, tmp_path, execute=True)
    assert again["status"] == "DONE_VERIFIED" and again["create_calls_this_run"] == 0
    assert gateway.calls == calls
    journal = next(tmp_path.glob("*.json"))
    assert journal.stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o700


@pytest.mark.asyncio
async def test_identical_source_sessions_are_not_deduplicated(tmp_path):
    items = [TransferItem("classic", name, 0, 0, {"title": "Same", "structure": [10]}) for name in ("a", "b")]
    gateway = FakeGateway(items)
    result = await transfer(request(), gateway, tmp_path, execute=True)
    assert result["status"] == "DONE_VERIFIED" and len(gateway.rows) == 2
    assert result["created_ids"]["classic:a"] != result["created_ids"]["classic:b"]


@pytest.mark.asyncio
async def test_wrong_digest_prevents_all_writes(tmp_path):
    gateway = FakeGateway()
    with pytest.raises(TransferError, match="Source changed") as error:
        await transfer(request(expected_source_digest="c" * 64), gateway, tmp_path, execute=True)
    assert error.value.code == "SOURCE_CHANGED" and gateway.calls == []


@pytest.mark.asyncio
async def test_new_request_cannot_duplicate_occupied_range(tmp_path):
    gateway = FakeGateway()
    await transfer(request(), gateway, tmp_path, execute=True)
    calls = list(gateway.calls)
    with pytest.raises(TransferError) as error:
        await transfer(request(request_id="new-request"), gateway, tmp_path, execute=True)
    assert error.value.code == "OCCUPIED_RANGE" and gateway.calls == calls
    result = await preview(request(), gateway)
    assert not result["ready"] and len(result["collisions"]) == 4


@pytest.mark.asyncio
async def test_timeout_after_success_reconciles_then_continues(tmp_path):
    gateway = FakeGateway()
    gateway.mode = "timeout-after"
    result = await transfer(request(), gateway, tmp_path, execute=True)
    assert result["status"] == "DONE_VERIFIED" and len(gateway.calls) == 4
    assert gateway.calls.count("c1") == 1


@pytest.mark.asyncio
async def test_unresolved_timeout_never_replays_create(tmp_path):
    gateway = FakeGateway()
    gateway.mode = "timeout-before"
    first = await transfer(request(), gateway, tmp_path, execute=True)
    assert first["status"] == "UNCERTAIN" and gateway.calls == ["c1"]
    gateway.mode = None
    second = await transfer(request(), gateway, tmp_path, execute=True)
    assert second["status"] == "UNCERTAIN" and gateway.calls == ["c1"]
    assert gateway.rows == []


@pytest.mark.asyncio
async def test_unresolved_write_reserves_range_across_new_request_ids(tmp_path):
    gateway = FakeGateway()
    gateway.mode = "timeout-before"
    assert (await transfer(request(), gateway, tmp_path, execute=True))["status"] == "UNCERTAIN"
    gateway.mode = None
    with pytest.raises(TransferError) as error:
        await transfer(request(request_id="different-request"), gateway, tmp_path, execute=True)
    assert error.value.code == "UNRESOLVED_OVERLAP" and gateway.calls == ["c1"]


@pytest.mark.asyncio
async def test_unresolved_write_does_not_block_disjoint_date_range(tmp_path):
    gateway = FakeGateway()
    gateway.mode = "timeout-before"
    await transfer(request(), gateway, tmp_path, execute=True)
    gateway.mode = None
    result = await transfer(request(request_id="disjoint", start_date="2027-03-01"), gateway, tmp_path, execute=True)
    assert result["status"] == "DONE_VERIFIED" and len(gateway.calls) == 5


@pytest.mark.asyncio
async def test_process_crash_after_effect_resumes_without_duplicate(tmp_path):
    gateway = FakeGateway()
    gateway.mode = "crash"
    with pytest.raises(ProcessCrash):
        await transfer(request(), gateway, tmp_path, execute=True)
    assert len(gateway.rows) == 1
    journal = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert journal["entries"]["classic:c1"]["state"] == "INTENT"
    result = await transfer(request(), gateway, tmp_path, execute=True)
    assert result["status"] == "DONE_VERIFIED" and gateway.calls.count("c1") == 1


@pytest.mark.asyncio
async def test_inventory_outage_after_success_resumes_by_readback(tmp_path):
    gateway = FakeGateway()
    gateway.mode = "inventory-down"
    result = await transfer(request(), gateway, tmp_path, execute=True)
    assert result["status"] == "UNCERTAIN" and len(gateway.calls) == 1
    gateway.mode, gateway.bad_inventory = None, False
    result = await transfer(request(), gateway, tmp_path, execute=True)
    assert result["status"] == "DONE_VERIFIED" and gateway.calls.count("c1") == 1


@pytest.mark.asyncio
async def test_completed_request_detects_destination_drift_without_repair(tmp_path):
    gateway = FakeGateway()
    await transfer(request(), gateway, tmp_path, execute=True)
    gateway.rows[0]["content"]["title"] = "Changed externally"
    with pytest.raises(TransferError) as error:
        await transfer(request(), gateway, tmp_path, execute=True)
    assert error.value.code == "DESTINATION_DRIFT" and len(gateway.calls) == 4


@pytest.mark.asyncio
async def test_source_change_during_copy_is_reported_with_created_ids(tmp_path):
    gateway = FakeGateway()
    gateway.source_change_after = 1
    with pytest.raises(TransferError) as error:
        await transfer(request(), gateway, tmp_path, execute=True)
    assert error.value.code == "SOURCE_CHANGED" and len(gateway.calls) == 4
    assert error.value.progress["status"] == "BLOCKED"
    assert len(error.value.progress["created_ids"]) == 4


@pytest.mark.asyncio
async def test_unknown_kind_fails_closed(tmp_path):
    gateway = FakeGateway([TransferItem("unknown", "x", 0, 0, {})])
    with pytest.raises(TransferError) as error:
        await transfer(request(), gateway, tmp_path, execute=True)
    assert error.value.code == "UNSUPPORTED_KIND" and gateway.calls == []


@pytest.mark.asyncio
async def test_request_id_cannot_be_rebound_to_new_dates(tmp_path):
    gateway = FakeGateway()
    await transfer(request(), gateway, tmp_path, execute=True)
    with pytest.raises(TransferError) as error:
        await transfer(request(start_date="2027-03-01"), gateway, tmp_path, execute=True)
    assert error.value.code == "JOURNAL_CONFLICT" and len(gateway.calls) == 4


@pytest.mark.asyncio
async def test_request_id_is_globally_bound_to_one_athlete(tmp_path):
    first = FakeGateway()
    await transfer(request(), first, tmp_path, execute=True)
    second = FakeGateway()
    with pytest.raises(TransferError) as error:
        await transfer(request(athlete_id=201), second, tmp_path, execute=True)
    assert error.value.code == "JOURNAL_CONFLICT" and second.calls == []
    assert len(list(tmp_path.glob("*.json"))) == 1


@pytest.mark.asyncio
async def test_semantic_mismatch_is_uncertain_and_never_recreated(tmp_path):
    gateway = FakeGateway()
    gateway.mode = "bad-readback"
    result = await transfer(request(), gateway, tmp_path, execute=True)
    assert result["status"] == "UNCERTAIN"
    gateway.mode = None
    result = await transfer(request(), gateway, tmp_path, execute=True)
    assert result["status"] == "UNCERTAIN" and len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_missing_visibility_is_not_assumed_false(tmp_path):
    gateway = FakeGateway()
    gateway.rows = [{"kind": "classic", "id": "existing", "date": "2027-02-01", "order": 0, "content": {}}]
    with pytest.raises(TransferError) as error:
        await transfer(request(), gateway, tmp_path, execute=True)
    assert error.value.code == "INVALID_INVENTORY" and gateway.calls == []


@pytest.mark.asyncio
async def test_attachment_requires_source_parent_before_any_writes(tmp_path):
    gateway = FakeGateway([TransferItem("attachment", "a", 0, 0, {}, "absent-note")])
    with pytest.raises(TransferError) as error:
        await transfer(request(), gateway, tmp_path, execute=True)
    assert error.value.code == "INVALID_PARENT" and gateway.calls == []


@pytest.mark.asyncio
async def test_all_visible_when_cutoff_is_omitted(tmp_path):
    gateway = FakeGateway()
    await transfer(request(visible_through=None), gateway, tmp_path, execute=True)
    assert all(row["hidden"] is False for row in gateway.rows)


@pytest.mark.asyncio
async def test_journal_symlink_is_rejected(tmp_path):
    gateway = FakeGateway()
    other = tmp_path / "other"
    other.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(other, target_is_directory=True)
    with pytest.raises(TransferError) as error:
        await transfer(request(), gateway, link, execute=True)
    assert error.value.code == "UNSAFE_JOURNAL" and gateway.calls == []
