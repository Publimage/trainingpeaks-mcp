"""Read and decode TrainingPeaks workout FIT files locally.

This is a read-only fallback for cases where TrainingPeaks' analysis API does
not expose chart data. The original device file is downloaded from the
workout, decoded on the MCP host, and never written back to TrainingPeaks.
"""
from __future__ import annotations

import gzip
import io
import json
import tempfile
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from typing import Any

from tp_mcp.client import TPClient

FIT_DATA_DIR = Path(tempfile.gettempdir()) / "tp-mcp" / "fit"
ALLOWED_SAMPLE_SECONDS = {1, 5, 10, 30, 60}
MAX_RECORDS_LIMIT = 5000
MAX_RAW_RECORDS = 100000


def _is_numeric_id(value: str, *, allow_negative: bool = False) -> bool:
    text = str(value).strip() if value is not None else ""
    if not text:
        return False
    return text.lstrip("-").isdigit() if allow_negative else text.isdigit()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _message_values(frame: Any) -> tuple[dict[str, Any], dict[str, str]]:
    values: dict[str, Any] = {}
    units: dict[str, str] = {}
    for field in frame.fields:
        name = str(field.name)
        value = _json_safe(field.value)
        if name in values:
            previous = values[name]
            if not isinstance(previous, list):
                values[name] = [previous]
            values[name].append(value)
        else:
            values[name] = value
        if field.units:
            units[name] = str(field.units)
    return values, units


def _elapsed_seconds(value: Any, origin: datetime | None, fallback: int) -> tuple[float, datetime | None]:
    if isinstance(value, datetime):
        if origin is None:
            origin = value
        return max(0.0, (value - origin).total_seconds()), origin
    return float(fallback), origin


def _decode_fit_bytes(
    payload: bytes,
    *,
    sample_seconds: int,
    start_seconds: float,
    end_seconds: float | None,
    max_records: int,
) -> dict[str, Any]:
    try:
        import fitdecode
    except ImportError as exc:
        raise RuntimeError("FIT decoder dependency is not installed on the MCP host.") from exc

    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    if not payload:
        raise ValueError("Downloaded FIT payload is empty.")

    message_counts: dict[str, int] = {}
    record_fields: set[str] = set()
    record_units: dict[str, str] = {}
    all_records: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    laps: list[dict[str, Any]] = []
    lengths: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    origin: datetime | None = None

    with fitdecode.FitReader(
        io.BytesIO(payload),
        check_crc=fitdecode.CrcCheck.WARN,
        error_handling=fitdecode.ErrorHandling.WARN,
    ) as reader:
        for frame in reader:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            name = str(frame.name)
            message_counts[name] = message_counts.get(name, 0) + 1
            values, units = _message_values(frame)

            if name == "record":
                if len(all_records) >= MAX_RAW_RECORDS:
                    raise ValueError(f"FIT file exceeds safe record limit ({MAX_RAW_RECORDS}).")
                timestamp_value = next(
                    (field.value for field in frame.fields if field.name == "timestamp"),
                    None,
                )
                elapsed, origin = _elapsed_seconds(timestamp_value, origin, len(all_records))
                values["elapsed_seconds"] = round(elapsed, 3)
                all_records.append(values)
                record_fields.update(values)
                record_units.update(units)
            elif name == "session":
                sessions.append(values)
            elif name == "lap":
                laps.append(values)
            elif name == "length":
                lengths.append(values)
            elif name == "event":
                events.append(values)

    selected: list[dict[str, Any]] = []
    last_bucket: int | None = None
    eligible_count = 0
    for record in all_records:
        elapsed = float(record.get("elapsed_seconds", 0.0))
        if elapsed < start_seconds:
            continue
        if end_seconds is not None and elapsed > end_seconds:
            continue
        bucket = int(elapsed // sample_seconds)
        if bucket == last_bucket:
            continue
        last_bucket = bucket
        eligible_count += 1
        if len(selected) < max_records:
            selected.append(record)

    FIT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "decoder": f"fitdecode {getattr(fitdecode, '__version__', 'unknown')}",
        "fit_size_bytes": len(payload),
        "message_counts": message_counts,
        "record_count_raw": len(all_records),
        "record_count_eligible": eligible_count,
        "record_fields": sorted(record_fields),
        "record_units": record_units,
        "sessions": sessions,
        "laps": laps,
        "lengths": lengths,
        "events": events,
        "records": selected,
        "truncated": eligible_count > len(selected),
        "_all_records": all_records,
    }


def _save_fit_json(workout_id: str, file_id: str, decoded: dict[str, Any]) -> str:
    FIT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = FIT_DATA_DIR / f"workout_{workout_id}_file_{file_id}.json"
    export = dict(decoded)
    export["records"] = export.pop("_all_records")
    path.write_text(json.dumps(export, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path.resolve())


def _fit_candidates(details: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key in ("workoutDeviceFileInfos", "attachmentFileInfos"):
        infos = details.get(key)
        if not isinstance(infos, list):
            continue
        for item in infos:
            if not isinstance(item, dict):
                continue
            file_id = item.get("fileId")
            file_name = str(item.get("fileName") or "")
            lower = file_name.lower()
            if file_id is not None and (lower.endswith(".fit") or lower.endswith(".fit.gz")):
                candidates.append(
                    {
                        "file_id": str(file_id),
                        "file_name": file_name or None,
                        "source": key,
                    }
                )
    return candidates


async def tp_get_workout_fit_data(
    workout_id: str,
    file_id: str | None = None,
    sample_seconds: int = 10,
    start_seconds: float = 0.0,
    end_seconds: float | None = None,
    max_records: int = 1800,
) -> dict[str, Any]:
    """Download and decode a workout's original FIT file without modifying it."""
    if not _is_numeric_id(workout_id):
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "workout_id must be numeric."}
    if file_id is not None and not _is_numeric_id(file_id, allow_negative=True):
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "file_id must be numeric."}
    if sample_seconds not in ALLOWED_SAMPLE_SECONDS:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": f"sample_seconds must be one of {sorted(ALLOWED_SAMPLE_SECONDS)}.",
        }
    if start_seconds < 0 or (end_seconds is not None and end_seconds < start_seconds):
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": "Use start_seconds >= 0 and end_seconds >= start_seconds.",
        }
    if not 1 <= max_records <= MAX_RECORDS_LIMIT:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": f"max_records must be between 1 and {MAX_RECORDS_LIMIT}.",
        }

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID", "message": "Could not resolve athlete ID."}

        details_endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}/details"
        details_response = await client.get(details_endpoint)
        if details_response.is_error:
            return {
                "isError": True,
                "error_code": details_response.error_code.value if details_response.error_code else "API_ERROR",
                "message": details_response.message,
            }
        details = details_response.data if isinstance(details_response.data, dict) else {}
        candidates = _fit_candidates(details)

        chosen = None
        if file_id is None:
            if len(candidates) != 1:
                return {
                    "isError": True,
                    "error_code": "FIT_FILE_SELECTION_REQUIRED",
                    "message": (
                        "Expected exactly one FIT file. Pass file_id explicitly."
                        if candidates
                        else "No FIT device/attachment file found for this workout."
                    ),
                    "fit_files": candidates,
                }
            chosen = candidates[0]
            file_id = chosen["file_id"]
        else:
            chosen = next((item for item in candidates if item["file_id"] == str(file_id)), None)

        raw_endpoint = f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}/rawfiledata/{file_id}"
        raw_response = await client.get_raw(raw_endpoint)
        if raw_response.is_error:
            return {
                "isError": True,
                "error_code": raw_response.error_code.value if raw_response.error_code else "API_ERROR",
                "message": raw_response.message,
            }

    try:
        decoded = _decode_fit_bytes(
            raw_response.content,
            sample_seconds=sample_seconds,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            max_records=max_records,
        )
        json_path = _save_fit_json(workout_id, str(file_id), decoded)
    except (OSError, ValueError, RuntimeError, gzip.BadGzipFile) as exc:
        return {"isError": True, "error_code": "FIT_DECODE_ERROR", "message": str(exc)}

    decoded.pop("_all_records", None)
    return {
        "workout_id": workout_id,
        "file_id": str(file_id),
        "file_name": chosen.get("file_name") if chosen else None,
        "content_type": raw_response.content_type,
        "sample_seconds": sample_seconds,
        "start_seconds": start_seconds,
        "end_seconds": end_seconds,
        "max_records": max_records,
        "full_json_path": json_path,
        **decoded,
    }
