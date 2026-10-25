"""Provider-independent, read-only target binding for IRONMAN requests.

No plan/athlete/template IDs are embedded in this module. Provider inventory
comes from the authenticated account on each request. A past manifest cannot
select a target. This module never grants permission to mutate a resource.
"""
from __future__ import annotations

import unicodedata
from typing import Any


class TargetStop(ValueError):
    def __init__(self, code: str, candidates: list[dict[str, Any]] | None = None):
        super().__init__(code)
        self.code = code
        self.candidates = candidates or []


def _positive_id(value: Any) -> bool:
    return type(value) is int and 0 < value <= (2**63 - 1)


def _label(value: Any) -> str:
    if type(value) is not str:
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _query(value: str | int) -> tuple[int | None, str]:
    if _positive_id(value):
        return value, ""
    if type(value) is not str or not value.strip() or len(value) > 200:
        raise TargetStop("TARGET_QUERY_REQUIRED")
    raw = value.strip()
    if raw.isdecimal():
        result = int(raw)
        if not _positive_id(result):
            raise TargetStop("TARGET_ID_INVALID")
        return result, ""
    normalized = _label(raw)
    if not normalized:
        raise TargetStop("TARGET_QUERY_REQUIRED")
    return None, normalized


def select_live_item(rows: list[dict[str, Any]], query: str | int,
                     *, id_field: str, title_field: str,
                     scope: str) -> dict[str, Any]:
    """Unique exact ID/name, then unique name fragment (>=4 chars).

    Ambiguous names are *never* resolved by provider ordering or old session
    state. The result only binds identity; permission remains a separate gate.
    """
    if type(rows) is not list or len(rows) > 10000:
        raise TargetStop("PROVIDER_INVENTORY_INVALID")
    if scope not in {"training_plan", "athlete", "workout_library",
                     "plan_workout", "plan_note", "athlete_workout"}:
        raise TargetStop("TARGET_KIND_UNSUPPORTED")
    wanted_id, wanted_name = _query(query)
    valid: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        if type(row) is not dict:
            raise TargetStop("PROVIDER_INVENTORY_INVALID")
        ident = row.get(id_field)
        if not _positive_id(ident):
            raise TargetStop("PROVIDER_ID_UNVERIFIABLE")
        if ident in seen:
            raise TargetStop("PROVIDER_DUPLICATE_IDS")
        seen.add(ident)
        valid.append(row)
    if wanted_id is not None:
        matches = [r for r in valid if r[id_field] == wanted_id]
        quality = "exact_id"
    else:
        matches = [r for r in valid if _label(r.get(title_field)) == wanted_name]
        quality = "exact_name"
        if not matches and len(wanted_name) >= 4:
            matches = [r for r in valid if wanted_name in _label(r.get(title_field))]
            quality = "unique_name_fragment"
    if not matches:
        raise TargetStop("TARGET_NOT_FOUND")
    if len(matches) != 1:
        candidates = [{"id": r[id_field], "name": r.get(title_field)}
                      for r in matches[:12]]
        raise TargetStop("TARGET_AMBIGUOUS", candidates)
    return {"record": dict(matches[0]), "match": quality,
            "scope": scope, "verified_from": "trainingpeaks_live_inventory"}


def resolve_plan_workout(rows: list[dict[str, Any]], query: str | int,
                         *, plan_id: int, week: int | None = None,
                         weekday: int | None = None) -> dict[str, Any]:
    """Resolve an EXISTING plan instance with an independently bound plan ID."""
    if not _positive_id(plan_id):
        raise TargetStop("PLAN_TARGET_REQUIRED")
    if (week is None) != (weekday is None):
        raise TargetStop("RELATIVE_SLOT_INCOMPLETE")
    if week is not None:
        if type(week) is not int or type(weekday) is not int or not 1 <= week <= 104 or not 1 <= weekday <= 7:
            raise TargetStop("RELATIVE_SLOT_INVALID")
        day = (week - 1) * 7 + weekday
        rows = [r for r in rows if type(r) is dict and r.get("day") == day]
    item = select_live_item(rows, query, id_field="workout_id",
                            title_field="title", scope="plan_workout")
    item["target"] = {"provider": "trainingpeaks", "container_kind": "training_plan",
                      "container_id": plan_id, "resource_id": item["record"]["workout_id"]}
    return item


def resolve_plan_note(rows: list[dict[str, Any]], query: str | int,
                      *, plan_id: int, week: int | None = None,
                      weekday: int | None = None) -> dict[str, Any]:
    """A native Plan Note is not an athlete note or a classic workout."""
    if not _positive_id(plan_id):
        raise TargetStop("PLAN_TARGET_REQUIRED")
    if (week is None) != (weekday is None):
        raise TargetStop("RELATIVE_SLOT_INCOMPLETE")
    if week is not None:
        if type(week) is not int or type(weekday) is not int or not 1 <= week <= 104 or not 1 <= weekday <= 7:
            raise TargetStop("RELATIVE_SLOT_INVALID")
        day = (week - 1) * 7 + weekday
        rows = [r for r in rows if type(r) is dict and r.get("day") == day]
    item = select_live_item(rows, query, id_field="note_id",
                            title_field="title", scope="plan_note")
    item["target"] = {"provider": "trainingpeaks", "container_kind": "training_plan",
                      "container_id": plan_id, "resource_id": item["record"]["note_id"]}
    return item


def require_new_name_absent(rows: list[dict[str, Any]], title: str,
                            *, id_field: str, title_field: str,
                            scope: str) -> dict[str, Any]:
    """Preflight new-resource intent with no imaginary provider resource ID."""
    if scope not in {"training_plan", "workout_library", "athlete_workout"}:
        raise TargetStop("CREATE_KIND_UNSUPPORTED")
    if type(title) is not str or not 1 <= len(title.strip()) <= 180:
        raise TargetStop("CREATE_TITLE_REQUIRED")
    if type(rows) is not list or any(type(x) is not dict or
                                     not _positive_id(x.get(id_field)) for x in rows):
        raise TargetStop("PROVIDER_INVENTORY_INVALID")
    normalized = _label(title)
    if any(_label(row.get(title_field)) == normalized for row in rows):
        raise TargetStop("CREATE_NAME_CONFLICT")
    return {"scope": scope, "intent": "create", "title": title.strip(),
            "provider_resource_id": None, "absence_checked": True,
            "verified_from": "trainingpeaks_live_inventory", "read_only": True}
