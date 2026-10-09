"""Inspect a LOCAL TrainingPeaks browser HAR without exposing credentials.

This is a diagnostic parser: it performs NO network requests, authentication,
or provider writes. It prints ONLY methods, hostnames, URL paths (no queries),
HTTP statuses and redacted JSON structures from relevant plan/strength calls.

Usage:
  python scripts/inspect_native_strength_capture.py --latest
  python scripts/inspect_native_strength_capture.py ~/Downloads/session.har

Export a Network HAR locally *after* saving a single update to the disposable
[MCP TEST] Training Plan 684543. NEVER send the raw HAR to ChatGPT/GitHub.
The HAR may contain authentication cookies/tokens. This script deliberately
does not print those values or upload the file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

PLAN_ID = 684543
MAX_FILE_BYTES = 50_000_000
ALLOWED_HOSTS = ("trainingpeaks.com", "peakswaresb.com")
RELEVANT = re.compile(r"(?:/plans/|workouts|strength|/rx/activity/|exerciselibrary)", re.I)
SECRET = re.compile(
    r"(?:auth|token|cookie|password|secret|authorization|session|credential|bearer|csrf|key)",
    re.I,
)


def latest_har() -> Path:
    home = Path.home()
    candidates = [
        p for folder in (home / "Downloads", home / "Desktop")
        if folder.is_dir()
        for p in folder.glob("*.har")
        if p.is_file()
    ]
    if not candidates:
        raise ValueError("Nessun .har in Download/Scrivania. Esporta il Network HAR dal browser.")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def parsed_json(body: object) -> object | None:
    if not isinstance(body, str) or not body or len(body) > 2_000_000:
        return None
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return None


def schema(value: object, level: int = 0, field: str = "") -> object:
    """Keep JSON shape, redact ALL free text and IDs except test plan identity."""
    if level >= 5:
        return "<nested>"
    if SECRET.search(field):
        return "<redacted>"
    if isinstance(value, dict):
        return {
            str(k)[:72]: schema(v, level + 1, str(k))
            for k, v in list(value.items())[:45]
        }
    if isinstance(value, list):
        return {"list_length": len(value),
                "example": schema(value[0], level + 1, field) if value else None}
    if isinstance(value, bool):
        return "<boolean>"
    if isinstance(value, (int, float)):
        return PLAN_ID if value == PLAN_ID else "<number>"
    if isinstance(value, str):
        if value == str(PLAN_ID):
            return str(PLAN_ID)
        if field.lower() in ("workouttype", "type", "blocktype"):
            return value[:55] if len(value) < 56 else "<string>"
        return "<string>"
    return "<null>" if value is None else "<other>"


def inspect(path: Path) -> int:
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("HAR mancante o troppo grande (max 50 MB).")
    with path.open(encoding="utf-8-sig") as handle:
        raw = json.load(handle)
    entries = raw.get("log", {}).get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("Formato HAR non valido.")
    records: list[dict[str, object]] = []
    for event in entries:
        request = event.get("request") or {}
        response = event.get("response") or {}
        url = urlsplit(str(request.get("url") or ""))
        host = (url.hostname or "").lower()
        if not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
            continue
        method = str(request.get("method") or "").upper()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            continue
        if SECRET.search(url.path):
            continue
        payload = parsed_json((request.get("postData") or {}).get("text"))
        # HAR paths may not contain the plan ID: it may appear only in POST JSON.
        same_plan = str(PLAN_ID) in url.path or (payload is not None and
                     str(PLAN_ID) in json.dumps(payload, ensure_ascii=False))
        related = bool(RELEVANT.search(url.path))
        if not (related or same_plan):
            continue
        rec: dict[str, object] = {
            "method": method,
            "host": host,
            "path": url.path[:280],  # no URL query or auth header values
            "status": response.get("status"),
            "test_plan_referenced": same_plan,
        }
        if payload is not None:
            rec["request_shape"] = schema(payload)
        # Response fields only: never dump provider data or bodies.
        result = parsed_json((response.get("content") or {}).get("text"))
        if isinstance(result, dict):
            rec["response_top_keys"] = list(result.keys())[:20]
            data = result.get("data")
            if isinstance(data, dict):
                rec["response_data_keys"] = list(data.keys())[:24]
        elif isinstance(result, list):
            rec["response_list_length"] = len(result)
        records.append(rec)
    # Preserve network ordering; prioritize saves, then test-plan reads.
    saves = [x for x in records if x["method"] in ("POST", "PUT", "PATCH")]
    related_reads = [x for x in records if x["method"] == "GET" and x["test_plan_referenced"]]
    other_reads = [x for x in records if x["method"] == "GET" and not x["test_plan_referenced"]]
    print(json.dumps({
        "status": "LOCAL_HAR_INSPECTION",
        "network_requests": len(entries),
        "relevant_requests": len(records),
        "matching_post_put_patch": len(saves),
        "notes": [
            "Nessuna richiesta al provider, nessuna modifica.",
            "Non condividere il file HAR originale: contiene potenzialmente credenziali.",
            "Condividere solo questo OUTPUT di riepilogo anonimizzato.",
        ],
        "requests": (saves + related_reads + other_reads)[:30],
    }, ensure_ascii=False, indent=2))
    return 0 if records else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("har_file", type=Path, nargs="?")
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args()
    try:
        path = latest_har() if args.latest or not args.har_file else args.har_file
        return inspect(path)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "STOP", "reason": str(error)[:250]},
                         ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
