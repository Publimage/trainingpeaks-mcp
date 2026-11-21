"""Offline contract tests for the complete TrainingPeaks copy adapter."""
from __future__ import annotations

import base64
import copy
import json
from types import SimpleNamespace

import pytest

from tp_mcp.client.http import APIResponse, RawResponse
from tp_mcp.tools.plan_transfer_core import TransferError, TransferRequest
from tp_mcp.tools.plan_transfer_provider import (
    OWNER_ID,
    TrainingPeaksTransferGateway,
    _classic,
    _native_payload,
    _note_orders,
    _pdf,
    _strength,
)

PLAN = 10
CALENDAR = 900
ATHLETE = 20
PDF = b"%PDF-1.4\n" + b"unrelated example content\n" * 8 + b"%%EOF\n"


def classic():
    return {"workoutId": 501, "workoutDay": "2027-01-06T00:00:00",
            "workoutTypeFamilyId": 1, "workoutTypeValueId": 1,
            "title": "Swim 1200m", "description": "A\n\nB", "orderOnDay": 0,
            "totalTimePlanned": 0.5, "distancePlanned": 1200,
            "isHidden": False, "isLocked": False,
            "structure": json.dumps({"structure": [{"length": 1200}], "polyline": "0,1"})}


def strength():
    return {"id": "601", "calendarId": CALENDAR, "workoutType": "StructuredStrength",
            "title": "Strength", "instructions": "Slow controlled movement",
            "prescribedDate": "2027-01-07", "prescribedDurationInSeconds": 1800,
            "prescribedTss": 15.0, "prescribedIntensityFactor": 0.4,
            "isHidden": False, "isLocked": False, "orderOnDay": 1,
            "complianceState": "NoCompletion",
            "blocks": [{"id": "block-old", "blockType": "SingleExercise", "title": "Squat",
                        "coachNotes": "Full range", "prescriptions": [{"id": "prescription-old",
                         "exercise": {"id": "6", "title": "Goblet Squat", "videoUrl": "https://example.test/video"},
                         "parameters": [{"parameter": "Reps", "inputFormat": "Integer"}],
                         "sets": [{"id": "set-old", "setOrigin": "Prescribed",
                                   "parameterValues": [{"id": "value-old", "parameter": "Reps",
                                                        "prescribedValue": "8", "executedValue": None}]}]}]}]}


def attachment():
    return {"id": 801, "fileName": "guide.pdf", "contentLength": len(PDF), "contentType": "application/pdf"}


def note():
    return {"id": 701, "noteDate": "2027-01-04T00:00:00", "title": "Start",
            "description": "Read this first.", "isHidden": False, "commentCount": 0,
            "attachments": [attachment()]}


class FakeClient:
    def __init__(self):
        self.reads = []
        self.writes = []
        self._athlete_id = None
        self._token_cache = SimpleNamespace(access_token="test-token")
        self.data = {
            "/users/v3/user": {"user": {"personId": OWNER_ID,
                "athletes": [{"athleteId": ATHLETE, "firstName": "Test", "lastName": "Athlete"}]}},
            "/plans/v1/plans": [{"planId": PLAN}],
            f"/plans/v1/plans/{PLAN}": {"planId": PLAN, "ownerPersonId": OWNER_ID,
                "planPersonId": CALENDAR, "title": "Example", "startDate": "2027-01-06",
                "weekCount": 1, "dayCount": 5, "workoutCount": 2, "isPublic": False},
            f"/plans/v1/plans/{PLAN}/workouts/2027-01-04/2027-01-11": [classic()],
            f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-01-11": [note()],
            f"/plans/v1/plans/{PLAN}/events/2027-01-04/2027-01-11": [],
            f"/plans/v1/plans/{PLAN}/calendarNote/701/attachments/801": {
                "fileName": "guide.pdf", "contentType": "application/pdf",
                "data": base64.b64encode(PDF).decode()},
            f"/fitness/v6/athletes/{ATHLETE}/workouts/2028-01-03/2028-01-09": [],
            f"/fitness/v2/athletes/{ATHLETE}/calendarNote/2028-01-03/2028-01-09": [],
            f"/fitness/v6/athletes/{ATHLETE}/events/2028-01-03/2028-01-09": [],
        }
        self.next_result = {"workoutId": 1501}
        self.raw = PDF

    async def get(self, path):
        self.reads.append(path)
        if path not in self.data:
            return APIResponse(success=False, message="No fixture")
        return APIResponse(success=True, data=copy.deepcopy(self.data[path]))

    async def _request(self, method, path, **kwargs):
        assert kwargs.get("_retry_on_401") is False
        assert "applyplan" not in path and method == "POST"
        self.writes.append((method, path, copy.deepcopy(kwargs["json"])))
        return APIResponse(success=True, data=copy.deepcopy(self.next_result))

    async def _ensure_access_token(self):
        return APIResponse(success=True)

    async def _throttle(self):
        pass

    async def get_raw(self, path):
        self.reads.append(path)
        return RawResponse(success=True, content=self.raw, content_type="application/pdf")


class FakeNative:
    def __init__(self):
        self.calls = []
        self.data = {
            f"/rx/activity/v1/workouts/calendar/{CALENDAR}/2027-01-04/2027-01-11": [{"id": "601"}],
            "/rx/activity/v1/workouts/601": strength(),
            f"/rx/activity/v1/workouts/calendar/{ATHLETE}/2028-01-03/2028-01-10": [],
        }

    async def request(self, method, url, **kwargs):
        path = url.split("https://api.peakswaresb.com", 1)[1]
        self.calls.append((method, path, copy.deepcopy(kwargs.get("json"))))
        value = self.data.get(path)
        if method == "POST":
            value = {**kwargs["json"], "id": "1601"}
        return SimpleNamespace(status_code=200 if value is not None else 404,
                               json=lambda: {"data": copy.deepcopy(value)})


@pytest.fixture
def setup_gateway():
    client, native = FakeClient(), FakeNative()
    gateway = TrainingPeaksTransferGateway(client, native)
    request = TransferRequest("test-transfer", PLAN, ATHLETE, "2028-01-03", "2028-01-05")
    return gateway, client, native, request


@pytest.mark.asyncio
async def test_complete_preflight_uses_plan_person_and_monday_anchor(setup_gateway):
    gateway, client, native, request = setup_gateway
    snapshot = await gateway.preflight(request)
    assert snapshot.anchor_date == "2027-01-04" and snapshot.day_count == 7
    assert {i.kind for i in snapshot.items} == {"classic", "strength", "note", "attachment"}
    assert next(i for i in snapshot.items if i.kind == "note").offset_days == 0
    assert next(i for i in snapshot.items if i.kind == "classic").offset_days == 2
    assert len(snapshot.digest) == 64
    assert any(f"calendar/{CALENDAR}/" in path for _, path, _ in native.calls)
    assert all(method == "GET" for method, _, _ in native.calls)
    assert client.writes == []
    assert await gateway.verify_source(snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation,code", [
    (lambda c: c.data["/users/v3/user"]["user"].update(personId=99), "COACH_IDENTITY_MISMATCH"),
    (lambda c: c.data["/users/v3/user"]["user"].update(athletes=[]), "ATHLETE_NOT_AUTHORIZED"),
    (lambda c: c.data[f"/plans/v1/plans/{PLAN}"].update(planPersonId=ATHLETE), "PLAN_CALENDAR_ID_INVALID"),
    (lambda c: c.data[f"/plans/v1/plans/{PLAN}"].update(workoutCount=5), "SOURCE_WORKOUT_COUNT_MISMATCH"),
    (lambda c: c.data[f"/plans/v1/plans/{PLAN}/workouts/2027-01-04/2027-01-11"][0].update(workoutTypeValueId=999),
     "UNSUPPORTED_CLASSIC_SPORT"),
    (lambda c: c.data[f"/plans/v1/plans/{PLAN}/workouts/2027-01-04/2027-01-11"][0].update(totalTimePlanned=None),
     "SWIM_PLANNED_FIELDS_MISSING"),
    (lambda c: c.data[f"/plans/v1/plans/{PLAN}/calendarNote/701/attachments/801"].update(data="invalidbase64"),
     "PDF_ENCODING_INVALID"),
])
async def test_source_failure_never_writes(setup_gateway, mutation, code):
    gateway, client, native, request = setup_gateway
    mutation(client)
    with pytest.raises(TransferError) as error:
        await gateway.preflight(request)
    assert error.value.code == code
    assert client.writes == [] and all(m == "GET" for m, _, _ in native.calls)


@pytest.mark.asyncio
async def test_other_workout_is_not_silently_dropped(setup_gateway):
    gateway, client, _, request = setup_gateway
    row = client.data[f"/plans/v1/plans/{PLAN}/workouts/2027-01-04/2027-01-11"][0]
    row.update(workoutTypeFamilyId=100, workoutTypeValueId=100, title="Mobility")
    snapshot = await gateway.preflight(request)
    assert next(i for i in snapshot.items if i.kind == "classic").content["workoutTypeValueId"] == 100


def test_native_clone_regenerates_document_ids_but_preserves_exercise_and_prescription():
    normalized = _strength(strength(), source=True)
    payload = _native_payload(normalized, ATHLETE, "2028-01-06", 1, True)
    assert payload["id"] != "601" and payload["calendarId"] == ATHLETE and payload["isHidden"] is True
    block = payload["blocks"][0]
    assert block["id"] != "block-old"
    prescription = block["prescriptions"][0]
    assert prescription["id"] != "prescription-old" and prescription["exercise"]["id"] == "6"
    assert prescription["exercise"]["videoUrl"] == "https://example.test/video"
    value = prescription["sets"][0]["parameterValues"][0]
    assert value["id"] != "value-old" and value["prescribedValue"] == "8" and value["executedValue"] is None
    assert _strength(payload, source=False) == normalized


@pytest.mark.asyncio
async def test_create_classic_is_one_shot_preserves_structure_and_visibility(setup_gateway):
    gateway, client, _, request = setup_gateway
    snapshot = await gateway.preflight(request)
    item = next(i for i in snapshot.items if i.kind == "classic")
    assert await gateway.create(request, item, "2028-01-05", False, None) == "1501"
    assert len(client.writes) == 1
    _, path, payload = client.writes[0]
    assert path == f"/fitness/v6/athletes/{ATHLETE}/workouts"
    assert payload["athleteId"] == ATHLETE and payload["workoutDay"] == "2028-01-05T00:00:00"
    assert payload["isHidden"] is False and "workoutId" not in payload
    assert json.loads(payload["structure"]) == item.content["structure"]
    assert payload["description"] == "A\n\nB"


@pytest.mark.asyncio
async def test_target_visibility_missing_is_not_assumed_false(setup_gateway):
    gateway, client, _, request = setup_gateway
    await gateway.preflight(request)
    row = classic()
    row.update(athleteId=ATHLETE, workoutDay="2028-01-05T00:00:00")
    del row["isHidden"]
    client.data[f"/fitness/v6/athletes/{ATHLETE}/workouts/2028-01-03/2028-01-09"] = [row]
    with pytest.raises(TransferError, match="visibility"):
        await gateway.inventory(request)
    assert client.writes == []


@pytest.mark.asyncio
async def test_target_attachment_is_verified_from_bytes(setup_gateway):
    gateway, client, _, request = setup_gateway
    snapshot = await gateway.preflight(request)
    row = note()
    row.update(id=1701, noteDate="2028-01-03T00:00:00")
    row["attachments"][0]["id"] = 1801
    client.data[f"/fitness/v2/athletes/{ATHLETE}/calendarNote/2028-01-03/2028-01-09"] = [row]
    actual = await gateway.inventory(request)
    copied = next(i for i in actual if i["kind"] == "attachment")
    expected = next(i for i in snapshot.items if i.kind == "attachment")
    assert copied["content"] == expected.content and copied["parent_id"] == "1701"
    assert any(path.endswith("/1701/attachments/1801/raw") for path in client.reads)
    client.raw = PDF.replace(b"example", b"changed")
    altered = await gateway.inventory(request)
    assert next(i for i in altered if i["kind"] == "attachment")["content"]["sha256"] != expected.content["sha256"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_result", [1801, "1801", {"id": 1801}])
async def test_attachment_create_rechecks_target_note_and_uses_original_bytes(setup_gateway, provider_result):
    gateway, client, _, request = setup_gateway
    snapshot = await gateway.preflight(request)
    item = next(i for i in snapshot.items if i.kind == "attachment")
    row = note()
    row.update(id=1701, noteDate="2028-01-03T00:00:00", attachments=[])
    client.data[f"/fitness/v1/athletes/{ATHLETE}/calendarNote/1701"] = row
    client.next_result = provider_result
    result = await gateway.create(request, item, "2028-01-03", False, "1701")
    assert result == "1801" and len(client.writes) == 1
    body = client.writes[0][2]
    assert body["noteId"] == 1701 and base64.b64decode(body["data"]) == PDF


@pytest.mark.asyncio
async def test_source_digest_detects_content_change(setup_gateway):
    gateway, client, _, request = setup_gateway
    snapshot = await gateway.preflight(request)
    client.data[f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-01-11"][0]["description"] = "Changed"
    assert not await gateway.verify_source(snapshot)


def test_pdf_validation_checks_metadata_size_magic_and_digest():
    expected = _pdf(PDF, attachment())
    assert expected["contentLength"] == len(PDF) and len(expected["sha256"]) == 64
    with pytest.raises(TransferError):
        _pdf(b"x" * len(PDF), attachment())
    with pytest.raises(TransferError):
        _pdf(PDF, {**attachment(), "contentLength": len(PDF) + 1})


def test_classic_completed_source_is_rejected():
    with pytest.raises(TransferError, match="completed"):
        _classic({**classic(), "totalTime": 1.0}, source=True)


@pytest.mark.parametrize("field,value", [
    ("attachmentFileInfos", [{"fileId": 123, "fileName": "prescription.pdf"}]),
    ("fileAttachments", "123"),
    ("workoutDeviceFileInfos", [{"fileId": 123, "fileName": "session.fit"}]),
])
def test_classic_other_attachment_shapes_fail_before_copy(field, value):
    with pytest.raises(TransferError, match="unsupported workout attachments"):
        _classic({**classic(), field: value}, source=True)


def test_classic_unknown_planned_field_is_not_silently_lost():
    with pytest.raises(TransferError, match="unsupported planned field"):
        _classic({**classic(), "newPrescriptionPlanned": 15}, source=True)


def test_classic_workout_comment_history_is_not_silently_lost():
    with pytest.raises(TransferError, match="unsupported workout comments"):
        _classic({**classic(), "workoutComments": [{"comment": "Athlete history"}]}, source=True)


@pytest.mark.asyncio
async def test_pool_length_and_code_are_copied_and_verified(setup_gateway):
    gateway, client, _, request = setup_gateway
    row = client.data[f"/plans/v1/plans/{PLAN}/workouts/2027-01-04/2027-01-11"][0]
    row.update(poolLengthOptionId=3, code="PRESET-12")
    snapshot = await gateway.preflight(request)
    item = next(i for i in snapshot.items if i.kind == "classic")
    await gateway.create(request, item, "2028-01-05", False, None)
    payload = client.writes[0][2]
    assert payload["poolLengthOptionId"] == 3 and payload["code"] == "PRESET-12"
    copied = {**payload, "workoutId": 1501}
    assert _classic(copied, source=False) == item.content
    copied["poolLengthOptionId"] = 2
    assert _classic(copied, source=False) != item.content


def test_note_order_uses_numeric_ids_not_input_or_lexicographic_order():
    notes = [{**note(), "id": nid} for nid in (10, 100, 9)]
    assert _note_orders(notes) == {"9": 0, "10": 1, "100": 2}
    with pytest.raises(TransferError, match="note order field unsupported"):
        _note_orders([{**note(), "orderOnDay": 1}])
    with pytest.raises(TransferError, match="note order id type unsupported"):
        _note_orders([{**note(), "id": "701"}])


@pytest.mark.asyncio
async def test_source_and_target_note_order_are_independently_ranked(setup_gateway):
    gateway, client, _, request = setup_gateway
    source = [{**note(), "id": 100, "title": "Second", "attachments": []},
              {**note(), "id": 9, "title": "First", "attachments": []}]
    client.data[f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-01-11"] = source
    snapshot = await gateway.preflight(request)
    notes = [item for item in snapshot.items if item.kind == "note"]
    assert [(item.content["title"], item.order) for item in notes] == [("First", 0), ("Second", 1)]
    target = [{**source[0], "id": 901, "noteDate": "2028-01-03T00:00:00"},
              {**source[1], "id": 900, "noteDate": "2028-01-03T00:00:00"}]
    client.data[f"/fitness/v2/athletes/{ATHLETE}/calendarNote/2028-01-03/2028-01-09"] = target
    actual = await gateway.inventory(request)
    assert {row["content"]["title"]: row["order"] for row in actual} == {"First": 0, "Second": 1}
    client.data[f"/fitness/v1/athletes/{ATHLETE}/calendarNote/901"] = target[0]
    client.data[f"/fitness/v2/athletes/{ATHLETE}/calendarNote/2028-01-03/2028-01-03"] = target
    assert (await gateway.read_item(request, notes[1], "901", None))["order"] == 1


@pytest.mark.asyncio
async def test_note_times_preserved_and_sorted_before_numeric_id(setup_gateway):
    gateway, client, _, request = setup_gateway
    source = [{**note(), "id": 100, "noteDate": "2027-01-04T06:30:00.123", "attachments": []},
              {**note(), "id": 9, "noteDate": "2027-01-04T18:45:00", "attachments": []}]
    client.data[f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-01-11"] = source
    snapshot = await gateway.preflight(request)
    notes = [item for item in snapshot.items if item.kind == "note"]
    assert [(item.source_id, item.order) for item in notes] == [("100", 0), ("9", 1)]
    assert notes[0].content["noteTime"] == "06:30:00.123"
    client.next_result = {"id": 900}
    await gateway.create(request, notes[0], "2028-01-03", False, None)
    payload = client.writes[0][2]
    assert payload["noteDate"] == "2028-01-03T06:30:00.123"
    assert "noteTime" not in payload and "orderOnDay" not in payload
    target = {**source[0], "id": 900, "noteDate": payload["noteDate"]}
    client.data[f"/fitness/v1/athletes/{ATHLETE}/calendarNote/900"] = target
    client.data[f"/fitness/v2/athletes/{ATHLETE}/calendarNote/2028-01-03/2028-01-03"] = [target]
    actual = await gateway.read_item(request, notes[0], "900", None)
    assert actual["content"] == notes[0].content
    target["noteDate"] = "2028-01-03T00:00:00"
    actual = await gateway.read_item(request, notes[0], "900", None)
    assert actual["content"] != notes[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value,code", [
    ("hasWeeklyGoals", True, "UNSUPPORTED_WEEKLY_GOALS"),
    ("planDescriptionAttachment", {"id": 123}, "UNSUPPORTED_PLAN_ATTACHMENT"),
])
async def test_unsupported_plan_extras_fail_before_writes(setup_gateway, field, value, code):
    gateway, client, native, request = setup_gateway
    client.data[f"/plans/v1/plans/{PLAN}"][field] = value
    with pytest.raises(TransferError) as error:
        await gateway.preflight(request)
    assert error.value.code == code
    assert client.writes == [] and all(method == "GET" for method, _, _ in native.calls)


@pytest.mark.asyncio
async def test_source_events_are_discovered_and_rejected_before_writes(setup_gateway):
    gateway, client, native, request = setup_gateway
    path = f"/plans/v1/plans/{PLAN}/events/2027-01-04/2027-01-11"
    client.data[path] = [{"id": 456, "name": "Race"}]
    with pytest.raises(TransferError) as error:
        await gateway.preflight(request)
    assert error.value.code == "UNSUPPORTED_SOURCE_EVENTS" and path in client.reads
    assert client.writes == [] and all(method == "GET" for method, _, _ in native.calls)
    del client.data[path]
    with pytest.raises(TransferError) as error:
        await gateway.preflight(request)
    assert error.value.code == "PROVIDER_READ_FAILED"


@pytest.mark.asyncio
async def test_target_events_are_not_treated_as_an_empty_calendar(setup_gateway):
    gateway, client, _, request = setup_gateway
    await gateway.preflight(request)
    client.data[f"/fitness/v6/athletes/{ATHLETE}/events/2028-01-03/2028-01-09"] = [{"id": 456}]
    with pytest.raises(TransferError) as error:
        await gateway.inventory(request)
    assert error.value.code == "UNSUPPORTED_TARGET_EVENTS"
    assert client.writes == []


@pytest.mark.asyncio
async def test_note_owner_and_timestamp_fail_before_writes(setup_gateway):
    gateway, client, _, request = setup_gateway
    row = client.data[f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-01-11"][0]
    row["planId"] = PLAN + 1
    with pytest.raises(TransferError) as error:
        await gateway.preflight(request)
    assert error.value.code == "NOTE_CALENDAR_IDENTITY_MISMATCH"
    row["planId"] = PLAN
    row["noteDate"] = "2027-01-04T25:00:00"
    with pytest.raises(TransferError) as error:
        await gateway.preflight(request)
    assert error.value.code == "NOTE_TIME_UNSUPPORTED"
    assert client.writes == []


@pytest.mark.asyncio
async def test_failed_new_preflight_invalidates_previous_binding(setup_gateway):
    gateway, client, _, request = setup_gateway
    snapshot = await gateway.preflight(request)
    item = next(item for item in snapshot.items if item.kind == "classic")
    client.data[f"/plans/v1/plans/{PLAN}"]["hasWeeklyGoals"] = True
    with pytest.raises(TransferError):
        await gateway.preflight(request)
    with pytest.raises(TransferError) as error:
        await gateway.create(request, item, "2028-01-05", False, None)
    assert error.value.code == "PREFLIGHT_REQUIRED"
    assert client.writes == []


@pytest.mark.asyncio
async def test_pdf_order_preserves_attachment_array_independent_of_parent_order(setup_gateway):
    gateway, client, _, request = setup_gateway
    original = note()
    original["attachments"] = [{**attachment(), "id": 100}, {**attachment(), "id": 9}]
    first = {**note(), "id": 700, "title": "Earlier note", "attachments": []}
    client.data[f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-01-11"] = [original, first]
    for aid in (100, 9):
        client.data[f"/plans/v1/plans/{PLAN}/calendarNote/701/attachments/{aid}"] = {
            "fileName": "guide.pdf", "contentType": "application/pdf",
            "data": base64.b64encode(PDF).decode()}
    snapshot = await gateway.preflight(request)
    items = [item for item in snapshot.items if item.kind == "attachment"]
    assert [(item.source_id, item.order) for item in items] == [("701/100", 0), ("701/9", 1)]
    assert next(item for item in snapshot.items if item.kind == "note" and item.source_id == "701").order == 1
    target = {**original, "id": 1701, "noteDate": "2028-01-03T00:00:00",
              "attachments": [{**attachment(), "id": 1801}, {**attachment(), "id": 1802}]}
    first_target = {**first, "id": 1700, "noteDate": target["noteDate"]}
    client.data[f"/fitness/v2/athletes/{ATHLETE}/calendarNote/2028-01-03/2028-01-09"] = [target, first_target]
    rows = [row for row in await gateway.inventory(request) if row["kind"] == "attachment"]
    assert [(row["id"], row["order"]) for row in rows] == [("1801", 0), ("1802", 1)]
    client.data[f"/fitness/v1/athletes/{ATHLETE}/calendarNote/1701"] = target
    client.data[f"/fitness/v2/athletes/{ATHLETE}/calendarNote/2028-01-03/2028-01-03"] = [target, first_target]
    assert (await gateway.read_item(request, items[0], "1801", "1701"))["order"] == 0
    target["attachments"].reverse()
    assert (await gateway.read_item(request, items[0], "1801", "1701"))["order"] == 1
