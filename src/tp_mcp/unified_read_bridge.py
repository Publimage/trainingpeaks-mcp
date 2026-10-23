"""Private VPC read-only transport for the ONE IRONMAN Prefect changeset flow.

The TP server keeps its credentials. Prefect receives only one explicitly
allowlisted plan/library resource at a time, without tokens or write endpoints.
This is an extension of the EXISTING IP-allowlisted private bridge, not a
separate service, general proxy, or shell.

No file-backed allowlist means NO unified reads.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCHEMA = "IRONMAN_UNIFIED_PRIVATE_READ_V1"
READ_PATH = "/v1/unified-resource-read"
READ_URL = "http://10.114.0.2:8787" + READ_PATH
REQUEST_MAX_BYTES = 4096
RESPONSE_MAX_BYTES = 2 * 1024 * 1024
OWNER = 2116886
KINDS = {
    "plan.workout.patch",
    "plan.note.patch",
    "plan.note.attachment.add",
    "plan.note.attachment.retire",
    "plan.strength.relocate",
    "library.workout.patch",
}
TARGET_FIELDS = {"provider", "owner_id", "container_kind", "container_id", "resource_id"}
POLICY_FIELDS = {"provider", "owner_id", "container_kind", "container_id", "kinds"}


def need(cond: bool, code: str) -> None:
    if not cond:
        raise ValueError(code)


def validate_spec(spec: Any) -> dict:
    need(type(spec) is dict and set(spec) == {"kind", "target"}, "UNIFIED_SPEC_FIELDS")
    target = spec["target"]
    need(type(target) is dict and set(target) == TARGET_FIELDS, "UNIFIED_TARGET_FIELDS")
    need(type(spec["kind"]) is str and spec["kind"] in KINDS, "UNIFIED_KIND")
    need(target["provider"] == "trainingpeaks"
         and type(target["owner_id"]) is int and target["owner_id"] == OWNER,
         "UNIFIED_PROVIDER_OWNER")
    need(target["container_kind"] in {"training_plan", "workout_library"},
         "UNIFIED_CONTAINER_KIND")
    need((spec["kind"].startswith("plan.") and target["container_kind"] == "training_plan")
         or (spec["kind"].startswith("library.") and target["container_kind"] == "workout_library"),
         "UNIFIED_KIND_CONTAINER")
    for key in ("container_id", "resource_id"):
        need(type(target[key]) is int and 0 < target[key] <= 2**63 - 1,
             "UNIFIED_TARGET_ID")
    return {"kind": spec["kind"], "target": dict(target)}


def validate_policy(raw: Any) -> list[dict]:
    need(type(raw) is list and len(raw) <= 128, "UNIFIED_POLICY_LIST")
    seen: set[tuple] = set()
    result: list[dict] = []
    for row in raw:
        need(type(row) is dict and set(row) == POLICY_FIELDS, "UNIFIED_POLICY_FIELDS")
        need(row["provider"] == "trainingpeaks" and
             type(row["owner_id"]) is int and row["owner_id"] == OWNER,
             "UNIFIED_POLICY_OWNER")
        need(row["container_kind"] in {"training_plan", "workout_library"},
             "UNIFIED_POLICY_CONTAINER")
        need(type(row["container_id"]) is int and 0 < row["container_id"] <= 2**63 - 1,
             "UNIFIED_POLICY_ID")
        kinds = row["kinds"]
        need(type(kinds) is list and 1 <= len(kinds) <= len(KINDS) and
             all(type(k) is str and k in KINDS for k in kinds) and
             len(set(kinds)) == len(kinds), "UNIFIED_POLICY_KINDS")
        need(all((k.startswith("plan.") and row["container_kind"] == "training_plan")
                 or (k.startswith("library.") and row["container_kind"] == "workout_library")
                 for k in kinds), "UNIFIED_POLICY_KIND_CONTAINER")
        key = (row["owner_id"], row["container_kind"], row["container_id"])
        need(key not in seen, "UNIFIED_POLICY_DUPLICATE")
        seen.add(key)
        result.append({**row, "kinds": list(kinds)})
    return result


def authorize(spec: Any, policy: Any) -> dict:
    """Deny outside the approved plan/library BEFORE contacting the provider."""
    parsed = validate_spec(spec)
    approved = validate_policy(policy)
    target = parsed["target"]
    for row in approved:
        if (row["owner_id"] == target["owner_id"] and
            row["container_kind"] == target["container_kind"] and
            row["container_id"] == target["container_id"] and
            parsed["kind"] in row["kinds"]):
            return parsed
    raise PermissionError("UNIFIED_RESOURCE_NOT_ALLOWED")


SENSITIVE_PROVIDER_KEYS = {
    "authorization", "accesstoken", "refreshtoken", "idtoken", "password",
    "secret", "cookie", "signedurl", "downloadurl", "contenturl",
    "presignedurl", "accessurl", "authheader", "apikey", "accesskey",
    "signeduri", "downloaduri", "uploadurl", "fileurl", "resourceurl",
    "href", "uri", "url", "link", "sessionid",
}


def project_read_record(raw: Any, depth: int = 0) -> Any:
    """Keep comparable provider fields; never move credentials or signed links.

    The projection is deterministic across identical provider reads, so the
    Prefect ledger can fingerprint and compare it. Reads are not a download API.
    """
    need(depth <= 32, "UNIFIED_RECORD_NESTING")
    if type(raw) is dict:
        need(len(raw) <= 500, "UNIFIED_RECORD_OBJECT_TOO_LARGE")
        return {key: project_read_record(value, depth + 1)
                for key, value in raw.items()
                if type(key) is str and
                re.sub(r"[^a-z0-9]", "", key.lower()) not in SENSITIVE_PROVIDER_KEYS
                and not key.lower().endswith(("signedurl", "downloadurl"))}
    if type(raw) is list:
        need(len(raw) <= 10000, "UNIFIED_RECORD_ARRAY_TOO_LARGE")
        return [project_read_record(item, depth + 1) for item in raw]
    need(raw is None or type(raw) in (str, int, float, bool),
         "UNIFIED_RECORD_UNSERIALIZABLE")
    return raw


async def build_private_read(payload: Any, policy: Any, read_item=None) -> dict:
    need(type(payload) is dict and set(payload) == {"spec"}, "UNIFIED_REQUEST_FIELDS")
    spec = authorize(payload["spec"], policy)
    if read_item is None:
        from scripts.ironman_jobs.ironman_unified_trainingpeaks_reads import read_trainingpeaks_item
        read_item = read_trainingpeaks_item
    item = await read_item(spec)
    need(type(item) is dict, "UNIFIED_PROVIDER_RECORD_SHAPE")
    result = {
        "schema": SCHEMA,
        "kind": spec["kind"],
        "target": spec["target"],
        "record": project_read_record(item),
        "trainingpeaks_writes": 0,
    }
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    need(len(encoded) <= RESPONSE_MAX_BYTES, "UNIFIED_RESPONSE_TOO_LARGE")
    return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _remote_read(spec: dict) -> dict:
    from scripts.ironman_jobs.ironman_unified_changeset_engine import ChangeStop, SecurityDenied
    validated = validate_spec(spec)
    raw = json.dumps({"spec": validated}, separators=(",", ":")).encode("utf-8")
    need(len(raw) <= REQUEST_MAX_BYTES, "UNIFIED_REQUEST_TOO_LARGE")
    req = Request(READ_URL, data=raw, method="POST",
                  headers={"Content-Type": "application/json"})
    # No redirects and no environment proxy: restricted private VPC destination.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=30) as response:
            need(response.status == 200, "UNIFIED_READ_HTTP_STATUS")
            result_bytes = response.read(RESPONSE_MAX_BYTES + 1)
    except HTTPError as error:
        if error.code in (401, 403):
            raise SecurityDenied("UNIFIED_BRIDGE_ACCESS_DENIED") from None
        if error.code in (408, 429, 502, 503, 504):
            raise ConnectionError("UNIFIED_BRIDGE_TEMPORARILY_UNAVAILABLE") from None
        raise ChangeStop("UNIFIED_BRIDGE_REJECTED") from None
    except (URLError, TimeoutError, ConnectionError):
        raise ConnectionError("UNIFIED_BRIDGE_TRANSPORT_UNAVAILABLE") from None
    need(len(result_bytes) <= RESPONSE_MAX_BYTES, "UNIFIED_READ_RESPONSE_TOO_LARGE")
    try:
        result = json.loads(result_bytes)
    except (ValueError, UnicodeDecodeError):
        raise ChangeStop("UNIFIED_BRIDGE_RESPONSE_INVALID") from None
    need(type(result) is dict and set(result) == {
        "schema", "kind", "target", "record", "trainingpeaks_writes"
    }, "UNIFIED_BRIDGE_RESPONSE_FIELDS")
    need(result["schema"] == SCHEMA and
         result["kind"] == validated["kind"] and
         result["target"] == validated["target"] and
         result["trainingpeaks_writes"] == 0 and
         type(result["record"]) is dict,
         "UNIFIED_BRIDGE_RESPONSE_MISMATCH")
    return result["record"]


class PrivateBridgeReadAdapter:
    """One adapter instance per resource type, shared by all plan/library IDs."""
    def read(self, spec: dict) -> dict:
        return _remote_read(spec)

    def apply(self, spec: dict) -> None:
        from scripts.ironman_jobs.ironman_unified_changeset_engine import SecurityDenied
        raise SecurityDenied("UNIFIED_PRIVATE_BRIDGE_WRITES_NOT_AUTHORIZED")
