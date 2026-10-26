"""Provider-independent identity and readback gates for new plans and deletion.

NO endpoints, tokens, network connections, POSTs or DELETEs live here.
The create route for arbitrary plans and the single-PLAN-workout delete route
are NOT provider-proven yet; this module can never authorize or perform them.
These gates are for independently canaried provider adapters in the future.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

OWNER = 2116886


class MutationStop(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def need(cond: bool, code: str) -> None:
    if not cond:
        raise MutationStop(code)


def digest(obj: Any) -> str:
    try:
        raw = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MutationStop("UNVERIFIABLE_PROVIDER_IMAGE") from exc
    return hashlib.sha256(raw.encode()).hexdigest()


def _id(x: Any) -> bool:
    return type(x) is int and 0 < x < 2**63


def _inventory(rows: Any) -> dict[int, dict[str, Any]]:
    need(type(rows) is list and len(rows) <= 10000, "INVENTORY_UNVERIFIABLE")
    output: dict[int, dict[str, Any]] = {}
    for row in rows:
        need(type(row) is dict and _id(row.get("planId")) and
             type(row.get("title")) is str, "INVENTORY_UNVERIFIABLE")
        plan_id = row["planId"]
        need(plan_id not in output, "DUPLICATE_PLAN_ID")
        output[plan_id] = row
    return output


def _create_spec(change: dict[str, Any]) -> tuple[str, int]:
    need(type(change) is dict and change.get("kind") == "plan.create" and
         type(change.get("target")) is dict, "CREATE_OPERATION_INVALID")
    t = change["target"]
    need(t == {"provider": "trainingpeaks", "owner_id": OWNER,
               "container_kind": "training_plan", "container_id": None,
               "resource_id": None}, "CREATE_TARGET_INVALID")
    p = change.get("payload")
    # A Training Plan is a dateless, reusable sequence of relative weeks/days.
    # The provider's private transport anchor never belongs in the request.
    need(type(p) is dict and set(p) == {"title", "week_count"},
         "CREATE_PAYLOAD_INVALID")
    title, count = p["title"], p["week_count"]
    need(type(title) is str and 1 <= len(title.strip()) <= 120,
         "CREATE_TITLE_INVALID")
    need(type(count) is int and 1 <= count <= 104, "CREATE_WEEKS_INVALID")
    need(type(change.get("before_sha256")) is str and
         len(change["before_sha256"]) == 64,
         "CREATE_PREIMAGE_REQUIRED")
    return title.strip(), count


def preview_new_plan(change: dict[str, Any], rows: list[dict[str, Any]],
                     *, coach_id: int) -> dict[str, Any]:
    """Plan creation preview, never creates a plan or grants publish rights."""
    need(type(coach_id) is int and coach_id == OWNER, "COACH_OWNER_MISMATCH")
    title, count = _create_spec(change)
    owned = _inventory(rows)
    need(digest(rows) == change["before_sha256"], "PLAN_INVENTORY_DRIFT")
    name = title.casefold()
    need(not any(str(p["title"]).strip().casefold() == name
                 for p in owned.values()), "PLAN_TITLE_ALREADY_EXISTS")
    return {"state": "CREATE_PREFLIGHT_ONLY", "provider_writes": 0,
            "publication_enabled": False, "title": title,
            "requested_weeks": count, "relative_weeks": count,
            "baseline_plan_ids": sorted(owned)}


def readback_new_plan(change: dict[str, Any], baseline: list[dict[str, Any]],
                      current: list[dict[str, Any]], detail: dict[str, Any],
                      *, coach_id: int) -> dict[str, Any]:
    """Verify an externally executed create; never claim this module wrote it."""
    preflight = preview_new_plan(change, baseline, coach_id=coach_id)
    previous, after = _inventory(baseline), _inventory(current)
    need(all(pid in after and after[pid] == old for pid, old in previous.items()),
         "UNRELATED_PLAN_CHANGED")
    created = [row for pid, row in after.items() if pid not in previous]
    need(len(created) == 1, "CREATE_PROVIDER_ID_UNVERIFIABLE")
    row = created[0]
    need(row["title"].strip() == preflight["title"], "CREATE_TITLE_DRIFT")
    need(row.get("isPublic") is False and row.get("price") in (None, 0, 0.0),
         "CREATE_INVENTORY_PRIVACY_DRIFT")
    need(type(detail) is dict and detail.get("planId") == row["planId"],
         "CREATE_DETAIL_IDENTITY_DRIFT")
    need(detail.get("title", "").strip() == preflight["title"],
         "CREATE_DETAIL_TITLE_DRIFT")
    need(detail.get("isPublic") is False and
         detail.get("price") in (None, 0, 0.0), "CREATE_PRIVACY_DRIFT")
    need(detail.get("weekCount") == preflight["requested_weeks"],
         "CREATE_WEEKS_DRIFT")
    # Provider startDate is only an internal API anchor, never a plan date.
    return {"state": "PROVIDER_READBACK_MATCH", "plan_id": row["planId"],
            "title": preflight["title"], "is_public": False,
            "relative_weeks": preflight["requested_weeks"],
            "writer_authorized_by_this_module": False}


def _workout_identity(row: Any) -> int | None:
    if type(row) is not dict:
        return None
    ids = [row[k] for k in ("workoutId", "planWorkoutId", "id")
           if _id(row.get(k))]
    return ids[0] if ids and len(set(ids)) == 1 else None


def _workout_map(rows: Any) -> dict[int, dict[str, Any]]:
    need(type(rows) is list and len(rows) <= 10000, "PLAN_WORKOUT_LIST_INVALID")
    output: dict[int, dict[str, Any]] = {}
    for w in rows:
        ident = _workout_identity(w)
        need(ident is not None and ident not in output, "PLAN_WORKOUT_ID_UNVERIFIABLE")
        output[ident] = w
    return output


def _without_transport_date(record: dict[str, Any]) -> dict[str, Any]:
    """Preserve relative slots/content, discard provider-only date coordinates."""
    need(type(record) is dict, "PROVIDER_RECORD_INVALID")
    return {k: v for k, v in record.items()
            if k not in ("startDate", "workoutDay", "noteDate", "date")}


def preview_delete_plan_workout(change: dict[str, Any], *, coach_id: int,
                                owned_plans: list[dict[str, Any]],
                                plan: dict[str, Any], workouts: list[dict[str, Any]],
                                notes: list[dict[str, Any]]) -> dict[str, Any]:
    """Read-only preflight; no athlete-calendar delete endpoints are used."""
    need(coach_id == OWNER and type(coach_id) is int, "COACH_OWNER_MISMATCH")
    need(type(change) is dict and change.get("kind") == "plan.workout.delete",
         "DELETE_KIND_INVALID")
    target = change.get("target")
    need(type(target) is dict and set(target) == {
        "provider", "owner_id", "container_kind", "container_id", "resource_id"
    }, "DELETE_TARGET_INVALID")
    need(target["provider"] == "trainingpeaks" and target["owner_id"] == OWNER
         and target["container_kind"] == "training_plan"
         and _id(target["container_id"]) and _id(target["resource_id"]),
         "DELETE_TARGET_INVALID")
    pid, wid = target["container_id"], target["resource_id"]
    owned = _inventory(owned_plans)
    need(pid in owned, "PLAN_NOT_OWNED_BY_COACH")
    need(type(plan) is dict and plan.get("planId") == pid,
         "DELETE_PLAN_ID_MISMATCH")
    need((owned[pid]["title"] or "").strip() == (plan.get("title") or "").strip() and
         owned[pid].get("isPublic") == plan.get("isPublic") and
         owned[pid].get("price") == plan.get("price"),
         "PLAN_INVENTORY_DETAIL_MISMATCH")
    # Commercial/public plan deletion needs a distinct, verified policy;
    # this conservative preflight does not extend its authorization.
    need(plan.get("isPublic") is False and plan.get("price") in (None, 0, 0.0),
         "DELETE_PLAN_PUBLIC_OR_PRICED")
    all_workouts = _workout_map(workouts)
    need(wid in all_workouts, "PLAN_WORKOUT_NOT_FOUND")
    selected = all_workouts[wid]
    p = change.get("payload")
    need(type(p) is dict and set(p) == {
         "expected_title", "week", "weekday"
    } and type(p["expected_title"]) is str
         and type(p["week"]) is int and 1 <= p["week"] <= 104
         and type(p["weekday"]) is int and 1 <= p["weekday"] <= 7,
         "DELETE_PAYLOAD_INVALID")
    relative_day = (p["week"] - 1) * 7 + p["weekday"]
    # The reader must provide the independently resolved relative slot.
    need((selected.get("title") or "").strip() == p["expected_title"].strip()
         and selected.get("week") == p["week"]
         and selected.get("day") == relative_day,
         "PLAN_WORKOUT_RELATIVE_SLOT_MISMATCH")
    need(type(change.get("before_sha256")) is str and
         change["before_sha256"] == digest(_without_transport_date(selected)), "PLAN_WORKOUT_PREIMAGE_DRIFT")
    need(type(notes) is list and all(type(n) is dict for n in notes),
         "PLAN_NOTES_UNVERIFIABLE")
    # Workouts/notes are verified separately. Preserve non-calendar plan
    # metadata explicitly: a previous provider PUT silently reset commercial
    # category, price and discovery fields even when workouts survived.
    # startDate and dayCount are technical/recomputed provider coordinates,
    # NOT canonical dates of a reusable Training Plan.
    protected_plan_fields = (
        "planId", "title", "description", "author", "planEmail",
        "planLanguage", "isPublic", "price", "isSearchable",
        "planCategory", "subcategory", "additionalCriteria",
        "customUrl", "sampleWeekOne", "sampleWeekTwo", "weekCount",
    )
    return {"state": "DELETE_PREFLIGHT_ONLY", "provider_writes": 0,
            "publication_enabled": False, "plan_id": pid, "workout_id": wid,
            "workout_count": len(all_workouts),
            "relative_week": p["week"], "relative_weekday": p["weekday"],
            "survivor_hashes": {str(k): digest(_without_transport_date(v))
                                for k, v in all_workouts.items() if k != wid},
            "note_sha256": digest([_without_transport_date(n) for n in notes]),
            "plan_identity": {k: plan.get(k) for k in protected_plan_fields}}


def verify_plan_workout_absent(preflight: dict[str, Any], *,
                               plan: dict[str, Any], workouts: list[dict[str, Any]],
                               notes: list[dict[str, Any]]) -> dict[str, Any]:
    """Postflight provider state comparison, not proof of who issued DELETE."""
    need(type(preflight) is dict and preflight.get("state") == "DELETE_PREFLIGHT_ONLY",
         "DELETE_PREFLIGHT_REQUIRED")
    observed = _workout_map(workouts)
    expected = preflight["survivor_hashes"]
    need(str(preflight["workout_id"]) not in {str(i) for i in observed},
         "TARGET_STILL_PRESENT")
    need({str(k): digest(_without_transport_date(v))
          for k, v in observed.items()} == expected and
         len(observed) == preflight["workout_count"] - 1,
         "OTHER_WORKOUTS_CHANGED")
    need(digest([_without_transport_date(n) for n in notes])
         == preflight["note_sha256"], "NATIVE_NOTES_CHANGED")
    need(type(plan) is dict and {k: plan.get(k) for k in preflight["plan_identity"]}
         == preflight["plan_identity"], "PLAN_METADATA_CHANGED")
    return {"state": "PROVIDER_POSTFLIGHT_MATCH",
            "plan_id": preflight["plan_id"],
            "absent_workout_id": preflight["workout_id"],
            "unrelated_workouts_preserved": len(observed),
            "native_notes_preserved": len(notes),
            "writer_authorized_by_this_module": False}
