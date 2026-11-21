"""TrainingPeaks adapter for complete, independent calendar copies.

The source plan is read only. Classic workouts, StructuredStrength, native notes
and PDF bytes use their existing separate provider routes. Native Apply/Unapply
is deliberately never called. Every mutation is one-shot; recovery belongs to
``plan_transfer_core`` and requires independent provider inventory.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import re
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any, cast

import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools.plan_transfer_core import PlanSnapshot, TransferError, TransferItem, TransferRequest
from tp_mcp.tools.strength import STRENGTH_API_BASE, _headers

OWNER_ID = 2116886
MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PLAN_DAYS = 730
MAX_ITEMS = 3000
_SPORTS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 100}
_CLASSIC_FIELDS = (
    "title", "description", "coachComments", "workoutTypeFamilyId",
    "workoutTypeValueId", "workoutSubTypeId", "totalTimePlanned",
    "distancePlanned", "tssPlanned", "ifPlanned", "velocityPlanned",
    "energyPlanned", "elevationGainPlanned", "workPlanned", "caloriesPlanned",
    "cadencePlanned", "userTags", "structure", "structuredWorkout", "isLocked",
    "poolLengthOptionId", "code",
)
_STRENGTH_FIELDS = (
    "title", "workoutType", "workoutSubTypeId", "instructions",
    "prescribedDurationInSeconds", "prescribedIntensityFactor", "prescribedTss",
    "isLocked",
)
_PLAN_FIELDS = (
    "planId", "ownerPersonId", "planPersonId", "title", "description",
    "startDate", "dayCount", "weekCount", "workoutCount", "isPublic", "price",
    "hasWeeklyGoals", "planDescriptionAttachment",
)


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise TransferError(code, code.replace("_", " ").lower())


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _identity(row: dict[str, Any], *keys: str) -> str:
    values = [str(row[k]) for k in keys if row.get(k) is not None]
    _need(bool(values) and len(set(values)) == 1 and values[0].isdigit()
          and int(values[0]) > 0, "AMBIGUOUS_PROVIDER_ID")
    return values[0]


def _day(value: Any) -> date:
    _need(isinstance(value, str), "PROVIDER_DATE_MISSING")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise TransferError("PROVIDER_DATE_INVALID", "Invalid provider date.") from exc


def _rows(data: Any, code: str) -> list[dict[str, Any]]:
    _need(isinstance(data, list) and len(data) <= MAX_ITEMS
          and all(isinstance(x, dict) for x in data), code)
    return data


def _order(row: dict[str, Any]) -> int:
    value = row.get("orderOnDay")
    _need(type(value) is int and value >= 0, "ORDER_NOT_READABLE")
    return cast(int, value)


def _note_time(row: dict[str, Any]) -> str:
    value = row.get("noteDate")
    _need(isinstance(value, str)
          and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,7})?(?:Z|[+-]\d\d:\d\d)?", value)
          is not None, "NOTE_TIME_UNSUPPORTED")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise TransferError("NOTE_TIME_UNSUPPORTED", "Unsupported note timestamp.") from exc
    return cast(str, value)[11:]


def _note_orders(notes: list[dict[str, Any]]) -> dict[str, int]:
    """Match the web comparator: same-day notes sort by time, then numeric ID.

    modules-cf37ed01.js (release 20261120), module 47126, deliberately excludes
    notes from _compareBySortOrder. _compareByTime compares timestamp suffixes
    as strings; _compareById then compares numeric note IDs.
    Do not send an invented note orderOnDay setting or trust arbitrary list order.
    """
    groups: dict[str, list[tuple[str, int]]] = {}
    for row in notes:
        nid = _identity(row, "id", "calendarNoteId", "noteId")
        _need(all(type(row[key]) is int for key in ("id", "calendarNoteId", "noteId")
                  if row.get(key) is not None), "NOTE_ORDER_ID_TYPE_UNSUPPORTED")
        _need(row.get("orderOnDay") in (None, 0), "NOTE_ORDER_FIELD_UNSUPPORTED")
        day = str(_day(row.get("noteDate")))
        groups.setdefault(day, []).append((_note_time(row), int(nid)))
    _need(sum(len(values) for values in groups.values())
          == len({nid for values in groups.values() for _, nid in values}), "DUPLICATE_NOTE_ID")
    return {str(nid): index for values in groups.values() for index, (_, nid) in enumerate(sorted(values))}


def _note_owner(row: dict[str, Any], owner: int, *, source: bool) -> None:
    key = "planId" if source else "athleteId"
    _need(row.get(key) is None or row[key] == owner, "NOTE_CALENDAR_IDENTITY_MISMATCH")


def _hidden(row: dict[str, Any]) -> bool:
    value = row.get("isHidden")
    _need(type(value) is bool, "VISIBILITY_NOT_READABLE")
    return cast(bool, value)


def _time(value: Any) -> str | None:
    if value is None or value == "":
        return None
    _need(isinstance(value, str), "PLANNED_TIME_INVALID")
    if re.match(r"^\d{4}-\d{2}-\d{2}T", value):
        _day(value)
        return "@DATE" + value[10:]
    _need(re.match(r"^\d\d:\d\d", value) is not None, "PLANNED_TIME_INVALID")
    return value


def _dated_time(value: str | None, target_date: str) -> str | None:
    return target_date + value[5:] if value and value.startswith("@DATE") else value


def _classic(row: dict[str, Any], *, source: bool) -> dict[str, Any]:
    _need(type(row.get("workoutTypeValueId")) is int
          and row["workoutTypeValueId"] in _SPORTS, "UNSUPPORTED_CLASSIC_SPORT")
    _need(isinstance(row.get("title"), str) and bool(row["title"].strip()), "WORKOUT_TITLE_MISSING")
    if source:
        _need(not row.get("completed") and not row.get("completedDate")
              and not row.get("totalTime") and not row.get("distance"), "SOURCE_HAS_COMPLETED_DATA")
        _need(not row.get("attachments") and not row.get("deviceFiles")
              and not row.get("attachmentFiles") and not row.get("attachmentFileInfos")
              and not row.get("fileAttachments") and not row.get("workoutDeviceFileInfos"),
              "UNSUPPORTED_WORKOUT_ATTACHMENTS")
        _need(not row.get("workoutComments"), "UNSUPPORTED_WORKOUT_COMMENTS")
        _need(not any(key.endswith("Planned") and value is not None and key not in _CLASSIC_FIELDS
                      and key != "startTimePlanned" for key, value in row.items()),
              "UNSUPPORTED_PLANNED_FIELD")
    result = {key: copy.deepcopy(row.get(key)) for key in _CLASSIC_FIELDS}
    for key in ("structure", "structuredWorkout"):
        if isinstance(result[key], str):
            try:
                result[key] = json.loads(result[key])
            except ValueError as exc:
                raise TransferError("INVALID_WORKOUT_STRUCTURE", "Structure JSON cannot be decoded.") from exc
    result["startTimePlanned"] = _time(row.get("startTimePlanned"))
    if row["workoutTypeValueId"] == 1:
        for key in ("totalTimePlanned", "distancePlanned"):
            value = row.get(key)
            _need(isinstance(value, (int, float)) and not isinstance(value, bool)
                  and math.isfinite(value) and value > 0,
                  "SWIM_PLANNED_FIELDS_MISSING")
    return result


def _strength_blocks(blocks: Any, *, source: bool) -> list[dict[str, Any]]:
    _need(isinstance(blocks, list) and bool(blocks), "STRENGTH_BLOCKS_MISSING")
    result = copy.deepcopy(blocks)
    for block in result:
        _need(isinstance(block, dict) and isinstance(block.get("prescriptions"), list),
              "STRENGTH_BLOCK_INVALID")
        nodes = [block]
        for prescription in block["prescriptions"]:
            _need(isinstance(prescription, dict)
                  and isinstance(prescription.get("exercise"), dict)
                  and prescription["exercise"].get("id") is not None
                  and isinstance(prescription.get("sets"), list), "STRENGTH_PRESCRIPTION_INVALID")
            nodes.append(prescription)
            for strength_set in prescription["sets"]:
                _need(isinstance(strength_set, dict)
                      and isinstance(strength_set.get("parameterValues"), list), "STRENGTH_SET_INVALID")
                nodes.append(strength_set)
                for value in strength_set["parameterValues"]:
                    _need(isinstance(value, dict) and isinstance(value.get("parameter"), str),
                          "STRENGTH_PARAMETER_INVALID")
                    if source:
                        _need(value.get("executedValue") is None, "SOURCE_HAS_COMPLETED_DATA")
                    value.pop("id", None)
                    value.pop("executedValue", None)
        for node in nodes:
            if source:
                _need(not node.get("isComplete"), "SOURCE_HAS_COMPLETED_DATA")
            node.pop("id", None)
            node.pop("isComplete", None)
    return result


def _strength(row: dict[str, Any], *, source: bool) -> dict[str, Any]:
    _need(row.get("workoutType") == "StructuredStrength", "UNSUPPORTED_NATIVE_WORKOUT")
    if source:
        _need(not row.get("files") and not row.get("executedDurationInSeconds")
              and row.get("complianceState") in (None, "NoCompletion"), "SOURCE_HAS_COMPLETED_DATA")
    result = {key: copy.deepcopy(row.get(key)) for key in _STRENGTH_FIELDS}
    result["prescribedStartTime"] = _time(row.get("prescribedStartTime"))
    result["blocks"] = _strength_blocks(row.get("blocks"), source=source)
    _need(isinstance(result["title"], str) and bool(result["title"].strip()), "WORKOUT_TITLE_MISSING")
    duration = result["prescribedDurationInSeconds"]
    _need(isinstance(duration, (int, float)) and not isinstance(duration, bool)
          and math.isfinite(duration) and duration > 0,
          "STRENGTH_DURATION_MISSING")
    return result


def _native_payload(content: dict[str, Any], athlete_id: int, target_date: str,
                    order: int, hidden: bool) -> dict[str, Any]:
    payload = {k: copy.deepcopy(v) for k, v in content.items() if v is not None}
    payload.update(id=str(uuid.uuid4()), calendarId=athlete_id, prescribedDate=target_date,
                   orderOnDay=order, isHidden=hidden)
    payload["prescribedStartTime"] = _dated_time(content.get("prescribedStartTime"), target_date)
    sets = 0
    for block in payload["blocks"]:
        block.update(id=str(uuid.uuid4()), isComplete=False)
        for prescription in block["prescriptions"]:
            prescription.update(id=str(uuid.uuid4()), isComplete=False)
            for strength_set in prescription["sets"]:
                strength_set.update(id=str(uuid.uuid4()), isComplete=False)
                sets += 1
                for value in strength_set["parameterValues"]:
                    value.update(id=str(uuid.uuid4()), executedValue=None)
    payload["snapshot"] = {"totalBlocks": len(payload["blocks"]), "completedBlocks": 0,
                           "totalSets": sets, "completedSets": 0}
    return payload


def _note(row: dict[str, Any]) -> dict[str, Any]:
    _need(isinstance(row.get("title"), str) and bool(row["title"].strip()), "NOTE_TITLE_MISSING")
    _need(row.get("description") is None or isinstance(row["description"], str), "NOTE_TEXT_INVALID")
    return {"title": row["title"], "description": row.get("description"), "noteTime": _note_time(row)}


def _pdf(blob: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    name, size, mime = metadata.get("fileName"), metadata.get("contentLength"), metadata.get("contentType")
    _need(isinstance(name, str) and name.lower().endswith(".pdf") and 1 <= len(name) <= 180
          and "/" not in name and "\\" not in name, "PDF_FILENAME_INVALID")
    _need(mime == "application/pdf" and type(size) is int and 100 <= size <= MAX_PDF_BYTES,
          "UNSUPPORTED_ATTACHMENT")
    _need(len(blob) == size and blob.startswith(b"%PDF-"), "PDF_BINARY_MISMATCH")
    return {"fileName": name, "contentType": mime, "contentLength": size,
            "sha256": hashlib.sha256(blob).hexdigest()}


class TrainingPeaksTransferGateway:
    """A single authenticated runtime; no source or destination is inferred.

    Public methods consume only typed requests. HTTP dependencies are injectable
    for offline tests. Attachment bytes never enter the persistent journal.
    """

    def __init__(self, client: TPClient | None = None, native_http: httpx.AsyncClient | None = None):
        self.client = client or TPClient()
        self.native_http = native_http or httpx.AsyncClient(timeout=45, follow_redirects=False)
        self._own_client = client is None
        self._own_http = native_http is None
        self._request: TransferRequest | None = None
        self._snapshot: PlanSnapshot | None = None
        self._pdf_bytes: dict[str, bytes] = {}
        self._native_cache: dict[str, tuple[str, dict[str, Any]]] = {}
        self.athlete_name = ""

    async def __aenter__(self) -> TrainingPeaksTransferGateway:
        if self._own_client:
            await self.client.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self._pdf_bytes.clear()
        self._native_cache.clear()
        if self._own_client:
            await self.client.__aexit__(exc_type, exc, traceback)
        if self._own_http:
            await self.native_http.aclose()

    async def _get(self, path: str, shape: type = dict) -> Any:
        response = await self.client.get(path)
        _need(not response.is_error and isinstance(response.data, shape), "PROVIDER_READ_FAILED")
        return response.data

    async def _native(self, method: str, path: str, payload: Any = None) -> Any:
        token_result = await self.client._ensure_access_token()
        _need(token_result.success and bool(self.client._token_cache.access_token), "AUTHENTICATION_FAILED")
        await self.client._throttle()
        response = await self.native_http.request(
            method, STRENGTH_API_BASE + path,
            headers=_headers(self.client._token_cache.access_token), json=payload,
        )
        # There are no mutation retries, including after 401 or a timeout.
        _need(response.status_code == 200, "NATIVE_PROVIDER_REJECTED")
        try:
            data = response.json()
        except ValueError as exc:
            raise TransferError("NATIVE_RESPONSE_INVALID", "Invalid native response.") from exc
        return data.get("data") if isinstance(data, dict) and "data" in data else data

    async def _authority(self, request: TransferRequest) -> None:
        data = await self._get("/users/v3/user")
        user = data.get("user", data)
        _need(isinstance(user, dict) and user.get("personId") == OWNER_ID, "COACH_IDENTITY_MISMATCH")
        roster = _rows(user.get("athletes"), "COACH_ROSTER_UNAVAILABLE")
        candidates = [a for a in roster if a.get("athleteId") == request.athlete_id
                      and (str(a.get("firstName") or "").strip() or str(a.get("lastName") or "").strip())]
        _need(len(candidates) == 1, "ATHLETE_NOT_AUTHORIZED")
        self.athlete_name = " ".join(str(candidates[0].get(k) or "").strip()
                                     for k in ("firstName", "lastName")).strip()
        self.client._athlete_id = request.athlete_id

    async def _source(self, request: TransferRequest, *, cache_bytes: bool) -> PlanSnapshot:
        owned = _rows(await self._get("/plans/v1/plans", list), "PLAN_INVENTORY_UNAVAILABLE")
        _need(sum(p.get("planId") == request.source_plan_id for p in owned) == 1, "PLAN_NOT_OWNED")
        plan = await self._get(f"/plans/v1/plans/{request.source_plan_id}")
        _need(plan.get("planId") == request.source_plan_id and plan.get("ownerPersonId") == OWNER_ID,
              "PLAN_IDENTITY_MISMATCH")
        _need(not plan.get("hasWeeklyGoals"), "UNSUPPORTED_WEEKLY_GOALS")
        _need(not plan.get("planDescriptionAttachment"), "UNSUPPORTED_PLAN_ATTACHMENT")
        calendar = plan.get("planPersonId")
        _need(type(calendar) is int and calendar > 0 and calendar != request.athlete_id,
              "PLAN_CALENDAR_ID_INVALID")
        technical_start = _day(plan.get("startDate"))
        anchor = technical_start - timedelta(days=technical_start.weekday())
        weeks, days = plan.get("weekCount"), plan.get("dayCount")
        _need(type(weeks) is int and weeks >= 0 and (days is None or type(days) is int), "PLAN_RANGE_INVALID")
        span = max(weeks * 7, (days or 0) + (technical_start - anchor).days)
        _need(0 < span <= MAX_PLAN_DAYS, "PLAN_RANGE_INVALID")
        end = anchor + timedelta(days=span)
        classic = _rows(await self._get(
            f"/plans/v1/plans/{request.source_plan_id}/workouts/{anchor}/{end}", list), "CLASSIC_INVENTORY_INVALID")
        strength = _rows(await self._native(
            "GET", f"/rx/activity/v1/workouts/calendar/{calendar}/{anchor}/{end}"), "STRENGTH_INVENTORY_INVALID")
        notes = _rows(await self._get(
            f"/plans/v1/plans/{request.source_plan_id}/calendarNote/{anchor}/{end}", list), "NOTE_INVENTORY_INVALID")
        events = _rows(await self._get(
            f"/plans/v1/plans/{request.source_plan_id}/events/{anchor}/{end}", list), "EVENT_INVENTORY_INVALID")
        _need(not events, "UNSUPPORTED_SOURCE_EVENTS")
        count = plan.get("workoutCount")
        _need(type(count) is int and count == len(classic) + len(strength), "SOURCE_WORKOUT_COUNT_MISMATCH")
        items: list[TransferItem] = []
        source_visibility: list[tuple[str, str, Any]] = []
        for row in classic:
            wid = _identity(row, "workoutId", "planWorkoutId", "id")
            offset = (_day(row.get("workoutDay")) - anchor).days
            _need(0 <= offset < span, "SOURCE_DATE_OUTSIDE_PLAN")
            items.append(TransferItem("classic", wid, offset, _order(row), _classic(row, source=True)))
            source_visibility.append(("classic", wid, row.get("isHidden")))
        for summary in strength:
            wid = _identity(summary, "id", "workoutId")
            row = await self._native("GET", f"/rx/activity/v1/workouts/{wid}")
            _need(isinstance(row, dict) and _identity(row, "id") == wid
                  and row.get("calendarId") == calendar, "SOURCE_STRENGTH_IDENTITY")
            offset = (_day(row.get("prescribedDate")) - anchor).days
            _need(0 <= offset < span, "SOURCE_DATE_OUTSIDE_PLAN")
            items.append(TransferItem("strength", wid, offset, _order(row), _strength(row, source=True)))
            source_visibility.append(("strength", wid, row.get("isHidden")))
        note_orders = _note_orders(notes)
        for row in notes:
            _note_owner(row, request.source_plan_id, source=True)
            nid = _identity(row, "id", "calendarNoteId", "noteId")
            offset = (_day(row.get("noteDate") or row.get("date")) - anchor).days
            _need(0 <= offset < span and not row.get("commentCount"), "UNSUPPORTED_SOURCE_NOTE")
            order = note_orders[nid]
            items.append(TransferItem("note", nid, offset, order, _note(row)))
            source_visibility.append(("note", nid, row.get("isHidden")))
            for attachment_order, attachment in enumerate(
                    _rows(row.get("attachments", []), "ATTACHMENT_INVENTORY_INVALID")):
                aid = _identity(attachment, "id", "attachmentId")
                data = await self._get(
                    f"/plans/v1/plans/{request.source_plan_id}/calendarNote/{nid}/attachments/{aid}")
                _need(data.get("fileName") == attachment.get("fileName")
                      and data.get("contentType") == "application/pdf" and isinstance(data.get("data"), str),
                      "SOURCE_PDF_METADATA_MISMATCH")
                _need(len(data["data"]) <= (MAX_PDF_BYTES + 2) // 3 * 4, "PDF_TOO_LARGE")
                try:
                    blob = base64.b64decode(data["data"], validate=True)
                except ValueError as exc:
                    raise TransferError("PDF_ENCODING_INVALID", "Invalid provider PDF encoding.") from exc
                content = _pdf(blob, attachment)
                key = f"{nid}/{aid}"
                if cache_bytes:
                    self._pdf_bytes[key] = blob
                items.append(TransferItem("attachment", key, offset, attachment_order, content, nid))
        _need(bool(items) and len(items) <= MAX_ITEMS, "SOURCE_EMPTY_OR_TOO_LARGE")
        _need(len({(item.kind, item.source_id) for item in items}) == len(items),
              "DUPLICATE_SOURCE_ID")
        items.sort(key=lambda item: (item.offset_days, item.order,
                                     ("classic", "strength", "note", "attachment").index(item.kind),
                                     item.source_id))
        source_visibility.sort()
        digest_data = {"plan": {k: plan.get(k) for k in _PLAN_FIELDS},
                       "items": [asdict(item) for item in items], "source_visibility": source_visibility}
        digest = hashlib.sha256(_json(digest_data).encode()).hexdigest()
        return PlanSnapshot(request.source_plan_id, plan["title"], anchor.isoformat(), span, digest, items)

    async def preflight(self, request: TransferRequest) -> PlanSnapshot:
        self._request, self._snapshot = None, None
        self._pdf_bytes.clear()
        await self._authority(request)
        snapshot = await self._source(request, cache_bytes=True)
        self._request, self._snapshot = request, snapshot
        return snapshot

    def _bound(self, request: TransferRequest) -> PlanSnapshot:
        _need(self._request == request and self._snapshot is not None, "PREFLIGHT_REQUIRED")
        return cast(PlanSnapshot, self._snapshot)

    async def inventory(self, request: TransferRequest) -> list[dict[str, Any]]:
        snapshot = self._bound(request)
        start = _day(request.start_date)
        end = start + timedelta(days=snapshot.day_count - 1)
        events = _rows(await self._get(
            f"/fitness/v6/athletes/{request.athlete_id}/events/{start}/{end}", list),
            "TARGET_EVENT_INVENTORY_INVALID")
        _need(not events, "UNSUPPORTED_TARGET_EVENTS")
        rows: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            upper = min(cursor + timedelta(days=89), end)
            classic = _rows(await self._get(
                f"/fitness/v6/athletes/{request.athlete_id}/workouts/{cursor}/{upper}", list),
                "TARGET_CLASSIC_INVENTORY_INVALID")
            for row in classic:
                _need(row.get("athleteId") == request.athlete_id, "TARGET_WORKOUT_IDENTITY")
                day = _day(row.get("workoutDay"))
                _need(cursor <= day <= upper, "TARGET_RANGE_DRIFT")
                rows.append({"kind": "classic", "id": _identity(row, "workoutId"), "date": str(day),
                             "order": _order(row), "hidden": _hidden(row), "content": _classic(row, source=False)})
            cursor = upper + timedelta(days=1)
        summaries = _rows(await self._native(
            "GET", f"/rx/activity/v1/workouts/calendar/{request.athlete_id}/{start}/{end + timedelta(days=1)}"),
            "TARGET_STRENGTH_INVENTORY_INVALID")
        for summary in summaries:
            wid = _identity(summary, "id", "workoutId")
            revision = summary.get("lastUpdatedAt")
            cached = self._native_cache.get(wid)
            if isinstance(revision, str) and revision and cached and cached[0] == revision:
                row = cached[1]
            else:
                row = await self._native("GET", f"/rx/activity/v1/workouts/{wid}")
                _need(isinstance(row, dict), "NATIVE_DETAIL_INVALID")
                if isinstance(revision, str) and revision:
                    self._native_cache[wid] = (revision, row)
            _need(_identity(row, "id") == wid and row.get("calendarId") == request.athlete_id,
                  "TARGET_STRENGTH_IDENTITY")
            day = _day(row.get("prescribedDate"))
            _need(start <= day <= end, "TARGET_RANGE_DRIFT")
            rows.append({"kind": "strength", "id": wid, "date": str(day), "order": _order(row),
                         "hidden": _hidden(row), "content": _strength(row, source=False)})
        notes = _rows(await self._get(
            f"/fitness/v2/athletes/{request.athlete_id}/calendarNote/{start}/{end}", list),
            "TARGET_NOTE_INVENTORY_INVALID")
        note_orders = _note_orders(notes)
        for row in notes:
            _note_owner(row, request.athlete_id, source=False)
            nid, day = _identity(row, "id", "calendarNoteId", "noteId"), _day(row.get("noteDate"))
            _need(start <= day <= end, "TARGET_RANGE_DRIFT")
            order, hidden = note_orders[nid], _hidden(row)
            rows.append({"kind": "note", "id": nid, "date": str(day), "order": order,
                         "hidden": hidden, "content": _note(row)})
            for attachment_order, attachment in enumerate(
                    _rows(row.get("attachments", []), "ATTACHMENT_INVENTORY_INVALID")):
                aid = _identity(attachment, "id", "attachmentId")
                # Exact native download route from the provider's current web
                # calendar-note model (modules-ef5eeb79.js, release 20261120).
                response = await self.client.get_raw(
                    f"/fitness/v1/athletes/{request.athlete_id}/calendarNote/{nid}/attachments/{aid}/raw")
                _need(not response.is_error, "TARGET_PDF_READ_FAILED")
                content = _pdf(response.content, attachment)
                rows.append({"kind": "attachment", "id": aid, "date": str(day), "order": attachment_order,
                             "hidden": hidden, "content": content, "parent_id": nid})
        return rows

    async def read_item(self, request: TransferRequest, item: TransferItem, target_id: str,
                        parent_target_id: str | None) -> dict[str, Any]:
        """Read only the newly created object; the core also performs a final full inventory."""
        self._bound(request)
        _need(isinstance(target_id, str) and target_id.isdigit() and int(target_id) > 0,
              "TARGET_ID_INVALID")
        if item.kind == "classic":
            row = await self._get(f"/fitness/v6/athletes/{request.athlete_id}/workouts/{target_id}")
            _need(_identity(row, "workoutId") == target_id and row.get("athleteId") == request.athlete_id,
                  "TARGET_WORKOUT_IDENTITY")
            return {"kind": "classic", "id": target_id, "date": str(_day(row.get("workoutDay"))),
                    "order": _order(row), "hidden": _hidden(row), "content": _classic(row, source=False)}
        if item.kind == "strength":
            row = await self._native("GET", f"/rx/activity/v1/workouts/{target_id}")
            _need(isinstance(row, dict) and _identity(row, "id") == target_id
                  and row.get("calendarId") == request.athlete_id, "TARGET_STRENGTH_IDENTITY")
            return {"kind": "strength", "id": target_id, "date": str(_day(row.get("prescribedDate"))),
                    "order": _order(row), "hidden": _hidden(row), "content": _strength(row, source=False)}
        nid = target_id if item.kind == "note" else parent_target_id
        _need(isinstance(nid, str) and nid.isdigit() and int(nid) > 0, "TARGET_NOTE_ID_MISSING")
        nid = cast(str, nid)
        note = await self._get(f"/fitness/v1/athletes/{request.athlete_id}/calendarNote/{nid}")
        _note_owner(note, request.athlete_id, source=False)
        _need(_identity(note, "id", "calendarNoteId") == nid, "TARGET_NOTE_IDENTITY_MISMATCH")
        day = str(_day(note.get("noteDate")))
        day_notes = _rows(await self._get(
            f"/fitness/v2/athletes/{request.athlete_id}/calendarNote/{day}/{day}", list),
            "TARGET_NOTE_INVENTORY_INVALID")
        for row in day_notes:
            _note_owner(row, request.athlete_id, source=False)
        orders = _note_orders(day_notes)
        _need(nid in orders, "TARGET_NOTE_IDENTITY_MISMATCH")
        base = {"kind": item.kind, "id": target_id, "date": day,
                "order": orders[nid], "hidden": _hidden(note)}
        if item.kind == "note":
            return {**base, "content": _note(note)}
        _need(item.kind == "attachment", "UNSUPPORTED_KIND")
        matches = [(index, attachment) for index, attachment in enumerate(
                   _rows(note.get("attachments", []), "ATTACHMENT_INVENTORY_INVALID"))
                   if _identity(attachment, "id", "attachmentId") == target_id]
        _need(len(matches) == 1, "TARGET_ATTACHMENT_IDENTITY_MISMATCH")
        response = await self.client.get_raw(
            f"/fitness/v1/athletes/{request.athlete_id}/calendarNote/{nid}/attachments/{target_id}/raw")
        _need(not response.is_error, "TARGET_PDF_READ_FAILED")
        return {**base, "parent_id": nid, "order": matches[0][0],
                "content": _pdf(response.content, matches[0][1])}

    async def create(self, request: TransferRequest, item: TransferItem, target_date: str,
                     hidden: bool, parent_target_id: str | None) -> str:
        snapshot = self._bound(request)
        _need(item in snapshot.items and type(hidden) is bool, "SOURCE_ITEM_NOT_BOUND")
        expected_date = _day(request.start_date) + timedelta(days=item.offset_days)
        _need(str(expected_date) == target_date, "TARGET_DATE_MISMATCH")
        expected_hidden = request.visible_through is not None and expected_date > _day(request.visible_through)
        _need(hidden is expected_hidden, "TARGET_VISIBILITY_MISMATCH")
        ids: tuple[str, ...]
        if item.kind == "strength":
            result = await self._native("POST", "/rx/activity/v1/workouts/save",
                                        _native_payload(item.content, request.athlete_id,
                                                        target_date, item.order, hidden))
            _need(isinstance(result, dict), "STRENGTH_CREATE_RESPONSE_INVALID")
            return _identity(result, "id")
        if item.kind == "classic":
            payload = {k: copy.deepcopy(v) for k, v in item.content.items() if v is not None}
            payload.update(athleteId=request.athlete_id, workoutDay=target_date + "T00:00:00",
                           orderOnDay=item.order, isHidden=hidden)
            if "startTimePlanned" in payload:
                payload["startTimePlanned"] = _dated_time(payload["startTimePlanned"], target_date)
            for key in ("structure", "structuredWorkout"):
                if isinstance(payload.get(key), (dict, list)):
                    payload[key] = json.dumps(payload[key], ensure_ascii=False)
            path, ids = f"/fitness/v6/athletes/{request.athlete_id}/workouts", ("workoutId",)
        elif item.kind == "note":
            payload = {"title": item.content["title"], "description": item.content["description"],
                       "athleteId": request.athlete_id,
                       "noteDate": target_date + "T" + item.content["noteTime"], "isHidden": hidden}
            path, ids = f"/fitness/v1/athletes/{request.athlete_id}/calendarNote", ("id", "calendarNoteId")
        elif item.kind == "attachment":
            _need(isinstance(parent_target_id, str) and parent_target_id.isdigit()
                  and int(parent_target_id) > 0, "TARGET_NOTE_ID_MISSING")
            note = await self._get(f"/fitness/v1/athletes/{request.athlete_id}/calendarNote/{parent_target_id}")
            _note_owner(note, request.athlete_id, source=False)
            source_note = next((x for x in snapshot.items if x.kind == "note"
                                and x.source_id == item.parent_source_id), None)
            _need(source_note is not None and _identity(note, "id", "calendarNoteId") == parent_target_id
                  and str(_day(note.get("noteDate"))) == target_date
                  and _note(note) == source_note.content and _hidden(note) is hidden,
                  "TARGET_NOTE_IDENTITY_MISMATCH")
            blob = self._pdf_bytes.get(item.source_id)
            _need(isinstance(blob, bytes) and _pdf(blob, item.content) == item.content, "SOURCE_PDF_NOT_BOUND")
            payload = {"athleteId": request.athlete_id, "noteId": int(parent_target_id),
                       "fileName": item.content["fileName"], "contentType": "application/pdf",
                       "data": base64.b64encode(blob).decode("ascii")}
            path = f"/fitness/v1/athletes/{request.athlete_id}/calendarNote/{parent_target_id}/attachments"
            ids = ("id", "attachmentId")
        else:
            raise TransferError("UNSUPPORTED_KIND", "Unsupported resource kind.")
        result = await self.client._request("POST", path, json=payload, _retry_on_401=False)
        _need(not result.is_error, "PROVIDER_CREATE_UNVERIFIED")
        # The provider note model's addCalendarNoteAttachment receives a scalar
        # attachment ID; older wrappers also returned a document containing it.
        if item.kind == "attachment" and type(result.data) in (str, int):
            return _identity({"id": result.data}, "id")
        _need(isinstance(result.data, dict), "PROVIDER_CREATE_UNVERIFIED")
        return _identity(result.data, *ids)

    async def verify_source(self, snapshot: PlanSnapshot) -> bool:
        _need(self._request is not None and self._snapshot == snapshot, "PREFLIGHT_REQUIRED")
        await self._authority(self._request)
        return (await self._source(self._request, cache_bytes=False)).digest == snapshot.digest
