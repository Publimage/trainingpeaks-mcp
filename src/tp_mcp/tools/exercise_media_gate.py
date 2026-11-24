"""One provider-neutral exercise/video release gate for every IRONMAN surface.

The deployment snapshot is a *derived* copy of approved Drive RESOURCE_LIBRARY
entries, not another coaching source of truth. The gate never selects a drill
from a generic prescription, changes dosage, or edits TrainingPeaks.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_CATALOG = Path(__file__).resolve().parents[3] / "data" / "ironman_approved_exercise_media_snapshot.json"
_URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_GENERIC_SWIM = re.compile(
    r"\b(?:tecnica\s+\d+\s*m\s*\+\s*completo|"
    r"tecnica\s+(?:presa|assetto|respirazione)|"
    r"tecnica\s+e\s+nuoto\s+completo|"
    r"(?:esegui|nuota)\s+\w*\s*(?:drill|eserciz\w*\s+tecnic\w*))\b",
    re.IGNORECASE,
)
_NEGATED_PREFIX = re.compile(
    r"\b(?:non\s+(?:aggiungere|eseguire|fare|inserire|prevedere|cercare)|"
    r"evita\s+(?:gli|i|di)|senza)\s*$", re.IGNORECASE,
)


class ExerciseMediaGateError(ValueError):
    """The athlete-facing exercise prescription is not ready to publish."""


def approved_media_snapshot() -> dict[str, Any]:
    data = json.loads(_CATALOG.read_text(encoding="utf-8"))
    if data.get("schema") != "IRONMAN_APPROVED_EXERCISE_MEDIA_SNAPSHOT_V1":
        raise ExerciseMediaGateError("MEDIA_CATALOG_SCHEMA_INVALID")
    resources = data.get("resources")
    if not isinstance(resources, list) or not resources:
        raise ExerciseMediaGateError("MEDIA_CATALOG_EMPTY")
    seen: set[str] = set()
    for item in resources:
        uid = item.get("uid")
        if (not isinstance(uid, str) or uid in seen or
            item.get("status") != "APPROVED" or
            not isinstance(item.get("url"), str) or
            not item["url"].startswith("https://") or
            not isinstance(item.get("source_doc_id"), str) or
            not item["source_doc_id"]):
            raise ExerciseMediaGateError("MEDIA_CATALOG_ITEM_INVALID")
        seen.add(uid)
    return data


def _prescriptive_section(description: str) -> str:
    """Focus on instructions, avoiding negative/educational mentions elsewhere."""
    match = re.search(
        r"(?im)^TECNICA E INDICAZIONI\s*$", description
    )
    if match is None:
        # Plain templates often do not have an athlete-facing section heading.
        return description
    tail = description[match.end():]
    return re.split(
        r"(?im)^(?:COSA OSSERVARE|ALIMENTAZIONE E IDRATAZIONE|FUELING|NOTE)\s*$",
        tail, maxsplit=1,
    )[0]


def audit_exercise_media(
    description: str | None,
    *,
    sport: str,
    surface: str,
    prescribed_uids: Sequence[str] = (),
    native_exercises: Sequence[Mapping[str, Any]] = (),
    catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure audit for athlete, library, plan and publisher descriptions.

    Explicit prescribed_uids are preferred: a label such as 'tecnica' is NOT a
    license to infer A-March or Sculling. Native Strength requires video identity
    and variant evidence for each supplied exercise. No athlete/provider I/O.
    """
    if not surface.strip():
        raise ExerciseMediaGateError("MEDIA_SURFACE_REQUIRED")
    if sport not in {"swim", "run", "strength", "bike", "other"}:
        raise ExerciseMediaGateError("MEDIA_SPORT_UNSUPPORTED")
    if description is not None and not isinstance(description, str):
        raise ExerciseMediaGateError("MEDIA_DESCRIPTION_INVALID")
    resources = (catalog or approved_media_snapshot()).get("resources", [])
    if not isinstance(resources, list):
        raise ExerciseMediaGateError("MEDIA_CATALOG_INVALID")
    items = [i for i in resources if isinstance(i, dict) and
             i.get("status") == "APPROVED" and i.get("discipline") == sport]
    by_uid = {i["uid"]: i for i in items}
    body = description or ""
    commands = _prescriptive_section(body)
    matched: set[str] = set(prescribed_uids)
    issues: list[str] = []
    if sport in {"swim", "run"}:
        for item in items:
            for alias in item.get("aliases", []):
                for m in re.finditer(
                    r"(?<![\w])" + re.escape(alias) + r"(?![\w])",
                    commands, re.IGNORECASE
                ):
                    context = commands[max(0, m.start() - 38):m.start()]
                    if not _NEGATED_PREFIX.search(context):
                        matched.add(item["uid"])
                        break
        for uid in sorted(matched):
            resource = by_uid.get(uid)
            if resource is None:
                issues.append("MEDIA_RESOURCE_NOT_APPROVED:" + uid)
            elif resource["url"] not in body:
                issues.append("MEDIA_APPROVED_VIDEO_MISSING:" + uid)
        if sport == "swim" and _GENERIC_SWIM.search(commands):
            # If no explicit named drill can be established, fail closed.
            if not any(uid.startswith("SWIM_") for uid in matched):
                issues.append("SWIM_DRILL_UNSPECIFIED")
    for exercise in native_exercises:
        if not isinstance(exercise, Mapping):
            issues.append("NATIVE_EXERCISE_INVALID")
            continue
        if not exercise.get("exercise_id") or not exercise.get("name"):
            issues.append("NATIVE_EXERCISE_ID_OR_NAME_MISSING")
        if not exercise.get("video_verified") or not exercise.get("variant_verified"):
            issues.append("NATIVE_EXERCISE_VIDEO_OR_VARIANT_UNVERIFIED")
    return {"surface": surface, "sport": sport, "matched_uids": sorted(matched),
            "issues": issues, "status": "PASS" if not issues else "BLOCK_RELEASE"}


def assert_exercise_media_ready(
    description: str | None, *, sport: str, surface: str,
    prescribed_uids: Sequence[str] = (),
    native_exercises: Sequence[Mapping[str, Any]] = (),
    catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = audit_exercise_media(
        description, sport=sport, surface=surface,
        prescribed_uids=prescribed_uids, native_exercises=native_exercises,
        catalog=catalog,
    )
    if report["status"] != "PASS":
        raise ExerciseMediaGateError(str(report))
    return report


def assert_exercise_description_preserved(
    source: Mapping[str, Any], destination: Mapping[str, Any], *,
    surface: str,
) -> None:
    """Fail if a copy silently omits or changes athlete-facing instruction text."""
    if not surface:
        raise ExerciseMediaGateError("MEDIA_SURFACE_REQUIRED")
    for key in ("description", "coachComments"):
        original = source.get(key)
        if original not in (None, "") and destination.get(key) != original:
            raise ExerciseMediaGateError(
                "MEDIA_DESCRIPTION_LOST_OR_CHANGED:" + key
            )
