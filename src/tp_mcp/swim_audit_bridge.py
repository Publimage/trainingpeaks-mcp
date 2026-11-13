"""Bounded read-only swim-template transport for the existing private bridge.

No credentials, private source records, writes, or administrative operations.
The existing bridge enforces its source-IP policy before calling this module.
The template allowlist is separate from the athlete allowlist and defaults off.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCHEMA = "IRONMAN_SWIM_BRIDGE_INPUT_V1"
BRIDGE_URL = "http://10.114.0.2:8787/v1/swim-audit-input"
MAX_BYTES = 2 * 1024 * 1024
TARGET_KEYS = {"provider", "owner_id", "resource_kind", "container_id", "workout_id"}
ITEM_KEYS = {"exerciseLibraryId", "exerciseLibraryItemId", "exerciseLibraryItemType",
             "workoutTypeId", "distancePlanned", "structure"}


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def validate_target(target: Any) -> dict[str, str]:
    _need(type(target) is dict and set(target) == TARGET_KEYS, "SWIM_TARGET_FIELDS")
    _need(target["provider"] == "trainingpeaks" and
          target["resource_kind"] == "library_template", "SWIM_TARGET_SCOPE")
    for key in ("owner_id", "container_id", "workout_id"):
        _need(type(target[key]) is str and
              re.fullmatch(r"[1-9][0-9]{0,19}", target[key]) is not None,
              "SWIM_TARGET_IDENTIFIER")
    return copy.deepcopy(target)


def validate_allowlist(value: Any) -> list[dict[str, str]]:
    _need(type(value) is list and len(value) <= 8, "SWIM_ALLOWLIST_INVALID")
    targets = [validate_target(target) for target in value]
    keys = [tuple(target[key] for key in sorted(TARGET_KEYS)) for target in targets]
    _need(len(keys) == len(set(keys)), "SWIM_ALLOWLIST_DUPLICATE")
    return targets


def _one(rows: Any, key: str, identifier: int) -> dict:
    _need(type(rows) is list and all(type(row) is dict for row in rows),
          "SWIM_PROVIDER_ROWS_INVALID")
    found = [row for row in rows if type(row.get(key)) is int and row[key] == identifier]
    _need(len(found) == 1, "SWIM_PROVIDER_ID_NOT_UNIQUE")
    return found[0]


def _validate_projection(library: Any, item: Any, target: dict[str, str]) -> None:
    _need(type(library) is dict and set(library) == {"exerciseLibraryId", "ownerId"},
          "SWIM_LIBRARY_PROJECTION")
    _need(type(item) is dict and set(item) == ITEM_KEYS, "SWIM_ITEM_PROJECTION")
    for record, key, expected in (
        (library, "exerciseLibraryId", target["container_id"]),
        (library, "ownerId", target["owner_id"]),
        (item, "exerciseLibraryId", target["container_id"]),
        (item, "exerciseLibraryItemId", target["workout_id"]),
    ):
        _need(type(record.get(key)) is int and record[key] == int(expected),
              "SWIM_PROVIDER_IDENTITY_MISMATCH")
    _need(item["exerciseLibraryItemType"] == "WorkoutTemplate" and
          type(item["workoutTypeId"]) is int and item["workoutTypeId"] == 1,
          "SWIM_PROVIDER_NOT_SWIM")


async def _rows(client: Any, endpoint: str) -> list:
    response = await client.get(endpoint)
    if getattr(response, "is_error", None) is not False:
        # Do not guess an authorization failure is a transient transport error.
        raise RuntimeError("SWIM_PROVIDER_READ_REJECTED")
    return response.data


def authorize_request(payload: Any, allowed_targets: Any) -> dict[str, str]:
    _need(type(payload) is dict and set(payload) == {"target"}, "SWIM_REQUEST_FIELDS")
    target = validate_target(payload["target"])
    if target not in validate_allowlist(allowed_targets):
        raise PermissionError("SWIM_TEMPLATE_NOT_ALLOWED")
    return target


async def build_swim_input(payload: Any, allowed_targets: Any, *, client: Any,
                           now_fn: Callable | None = None) -> dict:
    target = authorize_request(payload, allowed_targets)
    user = await client._get_user_data()
    if (type(user) is not dict or type(user.get("personId")) is not int
            or user["personId"] != int(target["owner_id"])):
        raise PermissionError("SWIM_CONNECTED_OWNER_MISMATCH")
    libraries = await _rows(client, "/exerciselibrary/v2/libraries")
    library = _one(libraries, "exerciseLibraryId", int(target["container_id"]))
    if type(library.get("ownerId")) is not int or library["ownerId"] != int(target["owner_id"]):
        raise PermissionError("SWIM_LIBRARY_OWNER_MISMATCH")
    items = await _rows(client, f"/exerciselibrary/v2/libraries/{target['container_id']}/items")
    item = _one(items, "exerciseLibraryItemId", int(target["workout_id"]))
    _need(set(item) >= ITEM_KEYS, "SWIM_PROVIDER_FIELDS_MISSING")
    library_out = {key: library[key] for key in ("exerciseLibraryId", "ownerId")}
    item_out = {key: item[key] for key in ITEM_KEYS}
    _validate_projection(library_out, item_out, target)
    now = (now_fn or (lambda: datetime.now(timezone.utc)))()
    _need(isinstance(now, datetime) and now.utcoffset() is not None, "SWIM_CLOCK_INVALID")
    result = {
        "schema": SCHEMA, "target": target,
        "library": library_out, "item": item_out,
        "projection": "AUDIT_FIELDS_V1",
        "fetched_at_utc": now.astimezone(timezone.utc).isoformat(),
        "trainingpeaks_writes": 0,
    }
    encoded = json.dumps(result, allow_nan=False, separators=(",", ":")).encode("utf-8")
    _need(len(encoded) <= MAX_BYTES, "SWIM_PROVIDER_RESPONSE_TOO_LARGE")
    return copy.deepcopy(result)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_read(payload: dict) -> dict:
    raw = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
    _need(len(raw) <= 4096, "SWIM_REQUEST_TOO_LARGE")
    request = Request(BRIDGE_URL, data=raw, method="POST",
                      headers={"Content-Type": "application/json"})
    # Preserve the existing VPC route; never forward through environment proxies.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            _need(response.status == 200, "SWIM_BRIDGE_HTTP_STATUS")
            data = response.read(MAX_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise PermissionError("SWIM_BRIDGE_ACCESS_DENIED") from None
        if exc.code == 503:
            raise ConnectionError("SWIM_BRIDGE_TEMPORARILY_UNAVAILABLE") from None
        raise RuntimeError("SWIM_BRIDGE_HTTP_REJECTED") from None
    except (URLError, TimeoutError, ConnectionError):
        raise ConnectionError("SWIM_BRIDGE_TRANSPORT_UNAVAILABLE") from None
    _need(len(data) <= MAX_BYTES, "SWIM_BRIDGE_RESPONSE_TOO_LARGE")
    return json.loads(data.decode("utf-8"))


class SwimAuditBridgeClient:
    """Implement only the two library GETs consumed by acquire_swim_audit.

    Each call makes a new bridge read, without caching. Returned rows are an
    explicit audit-field projection, not a full-workout export. Source-IP policy
    is the existing bridge boundary, not new cryptographic authentication.
    """

    def __init__(self, target: dict, *, transport: Callable | None = None,
                 now_fn: Callable | None = None):
        self.target = validate_target(target)
        self.transport = transport or _http_read
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    async def get(self, endpoint: str) -> Any:
        library_path = "/exerciselibrary/v2/libraries"
        item_path = f"{library_path}/{self.target['container_id']}/items"
        _need(endpoint in (library_path, item_path), "SWIM_ENDPOINT_NOT_ALLOWED")
        result = await asyncio.to_thread(self.transport, {"target": copy.deepcopy(self.target)})
        _need(type(result) is dict and set(result) == {
            "schema", "target", "library", "item", "projection", "fetched_at_utc",
            "trainingpeaks_writes"}, "SWIM_BRIDGE_ENVELOPE")
        _need(result["schema"] == SCHEMA and result["target"] == self.target and
              result["projection"] == "AUDIT_FIELDS_V1", "SWIM_BRIDGE_BINDING")
        _need(type(result["trainingpeaks_writes"]) is int and
              result["trainingpeaks_writes"] == 0, "SWIM_BRIDGE_WRITE_GUARD")
        _validate_projection(result["library"], result["item"], self.target)
        fetched = datetime.fromisoformat(result["fetched_at_utc"])
        now = self.now_fn()
        _need(fetched.utcoffset() is not None and now.utcoffset() is not None,
              "SWIM_BRIDGE_CLOCK_TIMEZONE")
        _need(0 <= (now - fetched).total_seconds() <= 60, "SWIM_BRIDGE_READ_NOT_FRESH")
        row = result["library"] if endpoint == library_path else result["item"]
        return SimpleNamespace(is_error=False, data=[copy.deepcopy(row)])
