"""Public transfer entry point and MCP dispatch, with an in-memory provider only."""
import copy
import json
from unittest.mock import AsyncMock, Mock

import pytest

from tp_mcp.client.context import athlete_override
from tp_mcp.server import call_tool, list_tools
from tp_mcp.tools import plan_transfer as public
from tp_mcp.tools.plan_transfer_core import PlanSnapshot, TransferError, TransferItem

DIGEST = "c" * 64
TOOL_NAME = "tp_copy_training_plan_to_athlete"
ARGS = {"plan_id": 100, "athlete_id": 200, "start_date": "2027-02-01", "request_id": "public-test"}


class MemoryGateway:
    def __init__(self):
        self.rows = []
        self.creates = 0
        self.requests = []
        self.failure = None
        self.uncertain = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def preflight(self, request):
        self.requests.append(request)
        if self.failure:
            raise self.failure
        return PlanSnapshot(100, "Offline fixture", "2027-01-04", 7, DIGEST,
                            [TransferItem("classic", "source-1", 0, 0, {"title": "Bike", "duration": 30})])

    async def inventory(self, request):
        return copy.deepcopy(self.rows)

    async def read_item(self, request, item, target_id, parent_target_id):
        return copy.deepcopy(next(r for r in self.rows if str(r["id"]) == target_id))

    async def create(self, request, item, target_date, hidden, parent_target_id):
        self.creates += 1
        if self.uncertain:
            raise TimeoutError("Uncertain provider commit")
        self.rows.append({"kind": item.kind, "id": 4000 + self.creates, "date": target_date,
                          "hidden": hidden, "order": item.order, "content": copy.deepcopy(item.content)})
        return self.rows[-1]["id"]

    async def verify_source(self, snapshot):
        return True


@pytest.fixture
def harness(monkeypatch, tmp_path):
    gateway = MemoryGateway()
    factory = Mock(return_value=gateway)
    state = tmp_path / "private-state"
    monkeypatch.setattr(public, "TrainingPeaksTransferGateway", factory)
    monkeypatch.setattr(public, "_state_directory", lambda: state)
    return gateway, factory, state


@pytest.mark.asyncio
async def test_default_public_call_is_preview_without_provider_writes(harness):
    gateway, _, state = harness
    result = await public.tp_copy_training_plan_to_athlete(**ARGS)
    assert result["status"] == "PREVIEW" and result["success"] and result["ready"]
    assert result["source_digest"] == DIGEST and result["linked_plan_application"] is False
    assert result["copy_mode"] == "independent_calendar_objects"
    assert gateway.creates == 0 and not state.exists()


@pytest.mark.asyncio
async def test_execute_and_replay_have_truthful_success_flags(harness):
    gateway, _, _ = harness
    result = await public.tp_copy_training_plan_to_athlete(**ARGS, execute=True, expected_source_digest=DIGEST)
    assert result["status"] == "DONE_VERIFIED" and result["success"]
    assert result["created_ids"] == {"classic:source-1": "4001"} and gateway.creates == 1
    again = await public.tp_copy_training_plan_to_athlete(**ARGS, execute=True, expected_source_digest=DIGEST)
    assert again["status"] == "DONE_VERIFIED" and again["success"]
    assert again["create_calls_this_run"] == 0 and gateway.creates == 1


@pytest.mark.asyncio
async def test_uncertain_result_is_error_and_keeps_same_request_for_recovery(harness):
    gateway, _, _ = harness
    gateway.uncertain = True
    result = await public.tp_copy_training_plan_to_athlete(**ARGS, execute=True, expected_source_digest=DIGEST)
    assert result["status"] == "UNCERTAIN" and result["isError"] and not result["success"]
    assert result["request_id"] == ARGS["request_id"] and result["next_step"]
    again = await public.tp_copy_training_plan_to_athlete(**ARGS, execute=True, expected_source_digest=DIGEST)
    assert again["status"] == "UNCERTAIN" and gateway.creates == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["true", 1, 0, None, [], {}])
async def test_invalid_execute_rejected_before_opening_provider(harness, value):
    gateway, factory, state = harness
    result = await public.tp_copy_training_plan_to_athlete(**ARGS, execute=value)
    assert result["isError"] and result["error_code"] == "INVALID_EXECUTE"
    factory.assert_not_called()
    assert gateway.creates == 0 and not state.exists()


@pytest.mark.asyncio
async def test_execute_requires_preview_digest(harness):
    gateway, _, state = harness
    result = await public.tp_copy_training_plan_to_athlete(**ARGS, execute=True)
    assert result["isError"] and result["error_code"] == "DIGEST_REQUIRED"
    assert gateway.requests == [] and gateway.creates == 0 and not state.exists()


@pytest.mark.asyncio
async def test_raw_provider_exception_does_not_leak_secrets_or_payload(harness):
    gateway, _, _ = harness
    gateway.failure = RuntimeError("Authorization: Bearer NEVER-RETURN-THIS; athlete private notes; raw body")
    result = await public.tp_copy_training_plan_to_athlete(**ARGS)
    assert result["isError"] and result["error_code"] == "TRANSFER_UNVERIFIED"
    rendered = json.dumps(result)
    assert "NEVER-RETURN-THIS" not in rendered and "private notes" not in rendered and "raw body" not in rendered
    assert result["request_id"] == ARGS["request_id"]


@pytest.mark.asyncio
async def test_controlled_failure_preserves_partial_progress(harness, monkeypatch):
    error = TransferError("DESTINATION_DRIFT", "A transferred object changed.")
    error.progress = {"status": "BLOCKED", "created_ids": {"classic:source-1": "4001"},
                      "unverified_ids": {"note:source-2": "5001"}, "next_step": "Inspect provider state."}
    monkeypatch.setattr(public, "transfer", AsyncMock(side_effect=error))
    result = await public.tp_copy_training_plan_to_athlete(**ARGS, execute=True, expected_source_digest=DIGEST)
    assert result["isError"] and not result["success"] and result["status"] == "BLOCKED"
    assert result["error_code"] == "DESTINATION_DRIFT"
    assert result["created_ids"] == error.progress["created_ids"]
    assert result["unverified_ids"] == error.progress["unverified_ids"]
    assert result["next_step"] == "Inspect provider state."


@pytest.mark.asyncio
async def test_occupied_preview_is_successful_inspection_but_not_ready(harness):
    gateway, _, _ = harness
    gateway.rows = [{"kind": "note", "id": 5000, "date": ARGS["start_date"], "order": 0,
                     "hidden": False, "content": {"title": "Existing"}}]
    result = await public.tp_copy_training_plan_to_athlete(**ARGS)
    assert result["status"] == "PREVIEW" and result["success"] and not result["ready"]
    assert len(result["collisions"]) == 1 and gateway.creates == 0


@pytest.mark.asyncio
async def test_schema_requires_explicit_target_and_does_not_expose_server_paths():
    matches = [tool for tool in await list_tools() if tool.name == TOOL_NAME]
    assert len(matches) == 1
    tool = matches[0]
    schema = tool.input_schema
    assert set(schema["required"]) == {"plan_id", "athlete_id", "start_date", "request_id"}
    assert schema["properties"]["execute"]["default"] is False
    assert schema["properties"]["athlete_id"]["minimum"] == 1
    assert "journal_dir" not in schema["properties"] and "athlete" not in schema["properties"]
    assert schema["additionalProperties"] is False
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True


@pytest.mark.asyncio
async def test_dispatch_uses_explicit_athlete_and_restores_ambient_selection(harness):
    gateway, _, _ = harness
    token = athlete_override.set("previous-athlete")
    try:
        result = json.loads((await call_tool(TOOL_NAME, {**ARGS, "athlete": "different-athlete"}))[0].text)
        assert result["status"] == "PREVIEW" and result["athlete_id"] == 200
        assert gateway.requests[0].athlete_id == 200
        assert athlete_override.get() == "previous-athlete"
    finally:
        athlete_override.reset(token)


@pytest.mark.asyncio
async def test_dispatch_rejects_missing_athlete_without_using_ambient_selection(harness):
    gateway, factory, _ = harness
    args = {key: value for key, value in ARGS.items() if key != "athlete_id"}
    result = json.loads((await call_tool(TOOL_NAME, args))[0].text)
    assert result["isError"] and result["error_code"] == "INVALID_ARGS"
    assert "athlete_id" in result["message"] and gateway.creates == 0
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_forwards_execute_digest_and_visibility_exactly(harness):
    gateway, _, _ = harness
    args = {**ARGS, "execute": True, "expected_source_digest": DIGEST, "visible_through": "2027-01-31"}
    result = json.loads((await call_tool(TOOL_NAME, args))[0].text)
    assert result["status"] == "DONE_VERIFIED" and result["success"]
    assert gateway.rows[0]["hidden"] is True
    assert gateway.requests[0].expected_source_digest == DIGEST
