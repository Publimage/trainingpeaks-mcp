"""Pure, safe preview of selective TrainingPeaks field edits.

No network, no writes. Intended for planning; provider writes must use a
separately tested plan-scoped UPDATE with fresh readback and rollback.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

SPORTS = {
    "swim": "swimming", "swimming": "swimming", "nuoto": "swimming",
    "bike": "cycling", "cycling": "cycling", "bici": "cycling",
    "run": "running", "running": "running", "corsa": "running",
    "strength": "strength", "forza": "strength", "other": "other",
}
RESOURCES = {"training_plan_workout", "training_plan_note"}
FIELDS = {"title", "description"}
OPERATIONS = {"set", "prepend", "append", "replace_text", "remove_prefix", "remove_suffix"}


class ScopeError(ValueError):
    """Fail closed on invalid or ambiguous selection."""


@dataclass(frozen=True)
class Record:
    uid: str
    resource: str
    week: int
    sport: str
    provider_id: int
    locale: str
    fields: Mapping[str, str]


@dataclass(frozen=True)
class Edit:
    field: str
    operation: str
    text: str = ""
    find: str = ""


def normalize_sport(value: str) -> str:
    found = SPORTS.get(value.strip().lower())
    if found is None:
        raise ScopeError(f"Unknown sport: {value}")
    return found


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def apply_text(before: str, edit: Edit) -> tuple[str, str]:
    if edit.field not in FIELDS or edit.operation not in OPERATIONS:
        raise ScopeError("Unsupported field or operation")
    if not isinstance(before, str):
        raise ScopeError("Expected text field")
    if edit.operation == "set":
        if not edit.text.strip():
            raise ScopeError("Empty replacement refused")
        after = edit.text
    elif edit.operation == "prepend":
        if not edit.text:
            raise ScopeError("Empty prefix")
        after = before if before.startswith(edit.text) else edit.text + before
    elif edit.operation == "append":
        if not edit.text:
            raise ScopeError("Empty suffix")
        after = before if before.endswith(edit.text) else before + edit.text
    elif edit.operation == "replace_text":
        if not edit.find or not edit.text or edit.find not in before:
            raise ScopeError("Exact nonempty matching phrase required")
        after = before.replace(edit.find, edit.text)
    elif edit.operation == "remove_prefix":
        if not edit.text or not before.startswith(edit.text):
            raise ScopeError("Expected prefix absent")
        after = before[len(edit.text):]
    else:
        if not edit.text or not before.endswith(edit.text):
            raise ScopeError("Expected suffix absent")
        after = before[:-len(edit.text)]
    if not after.strip():
        raise ScopeError("Change would empty a field")
    return after, ("unchanged" if after == before else "change")


def preview(
    records: list[Record], *, resource: str, locale: str,
    expected_count: int, edit: Edit, sports: list[str] | None = None,
    weeks: list[int] | None = None, uids: list[str] | None = None,
) -> dict:
    if resource not in RESOURCES or not locale or expected_count <= 0:
        raise ScopeError("Exact resource, locale and expected count are required")
    if not any((sports, weeks, uids)) and expected_count != len(records):
        raise ScopeError("Whole-scope selection requires exact inventory count")
    selected_sports = {normalize_sport(s) for s in sports} if sports else None
    selected_weeks = set(weeks) if weeks else None
    selected_uids = set(uids) if uids else None
    selected = [
        r for r in records if r.resource == resource and r.locale == locale
        and (selected_sports is None or r.sport in selected_sports)
        and (selected_weeks is None or r.week in selected_weeks)
        and (selected_uids is None or r.uid in selected_uids)
    ]
    if len(selected) != expected_count:
        raise ScopeError(f"Count mismatch: {len(selected)} instead of {expected_count}")
    if len({r.uid for r in selected}) != len(selected):
        raise ScopeError("Duplicate canonical UID")
    if len({r.provider_id for r in selected}) != len(selected):
        raise ScopeError("Duplicate provider ID")
    diffs = []
    for r in selected:
        if edit.field not in r.fields:
            raise ScopeError(f"Missing {edit.field}: {r.uid}")
        before = r.fields[edit.field]
        after, status = apply_text(before, edit)
        diffs.append({
            "uid": r.uid, "provider_id": r.provider_id, "week": r.week,
            "sport": r.sport, "locale": r.locale, "field": edit.field,
            "before": before, "after": after, "sha256": digest(before),
            "status": status,
        })
    return {
        "scope": resource, "locale": locale, "selected": len(selected),
        "changed": sum(d["status"] == "change" for d in diffs),
        "provider_writes": 0, "verified_live": False, "diffs": diffs,
    }


def invalidate_translations(entries: list[dict], uid: str, field: str, source_text: str) -> list[dict]:
    """Italian source edits flag dependent translations; never overwrite translations."""
    result = [dict(item) for item in entries]
    for entry in result:
        if (entry.get("uid"), entry.get("field")) == (uid, field) and entry.get("locale") != "it-IT":
            if entry.get("source_hash") != digest(source_text):
                entry["status"] = "STALE"
    return result
