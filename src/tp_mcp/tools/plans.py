"""Training Plan tools — list/read authored multi-week plans + apply to an athlete.

TrainingPeaks training plans (Plan Store / "My Plans") are a separate entity from
workout libraries (exerciselibrary) and the ATP. Endpoints (tpapi):
  GET  /plans/v1/plans                                  → authored plans
  GET  /plans/v1/plans/{id}                             → plan summary
  GET  /plans/v1/plans/{id}/workouts/{start}/{end}      → all plan workouts (w/ structure)

Workouts are anchored at the plan's startDate; ``workoutDay`` gives the relative
day (day 1 = startDate). ``tp_apply_training_plan`` materialises the plan on an
athlete's calendar by COPYING each workout to ``start_date + relative_offset``
via the proven create endpoint (POST /fitness/v6/athletes/{id}/workouts) — there
is no black-box-discoverable native "apply" endpoint, so this is a faithful
client-side copy (structure/description/TSS preserved; TP does not record it as a
linked plan application).
"""

import json
import logging
from datetime import date as date_type
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from tp_mcp.client import TPClient
from tp_mcp.tools._validation import format_validation_error

logger = logging.getLogger("tp-mcp")

# workoutTypeValueId → sport label (mirrors SPORT_TYPE_MAP in workouts.py; for all
# standard sports the family id equals the value id, so family = value on create).
# Isolated staging plan for a four-week canonical archive pilot.
# It is private, unpriced, and may eventually cover all 24 weeks.
_INTERMEDIATE_PILOT_TITLE = "[MCP TEST] IRONMAN Intermediate 24W - Archive Pilot"
_INTERMEDIATE_PILOT_START = date_type(2027, 1, 4)
_INTERMEDIATE_PILOT_WEEKS = 24
_INTERMEDIATE_PILOT_FIRST_UID = "IMINT24W-W01-MON-OTHER-01"


_SPORT_BY_TYPE: dict[int, str] = {
    1: "Swim", 2: "Bike", 3: "Run", 4: "Brick", 5: "Crosstrain", 6: "Race",
    7: "DayOff", 8: "MtnBike", 9: "Strength", 11: "XCSki", 12: "Rowing", 13: "Walk",
    100: "Other",
}

# workoutTypeValueId 100 ("Other") is used by plans for training-PERIOD annotations
# (e.g. «Период: базовый») — calendar banners, not trainable sessions. They can't
# be replicated as workouts on apply (TP renders them as period bands), so apply
# skips them rather than creating junk calendar entries.
_PERIOD_TYPE_ID = 100


def _err(code: str, msg: str | None) -> dict[str, Any]:
    return {"isError": True, "error_code": code, "message": msg or "error"}


def _api_err(response: Any) -> dict[str, Any]:
    return _err(response.error_code.value if response.error_code else "API_ERROR",
                response.message)


class _PlanIdInput(BaseModel):
    plan_id: int = Field(gt=0)

    @field_validator("plan_id", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> object:
        return int(v) if isinstance(v, str) else v


class _ApplyInput(BaseModel):
    plan_id: int = Field(gt=0)
    start_date: date_type

    @field_validator("plan_id", mode="before")
    @classmethod
    def _coerce_id(cls, v: object) -> object:
        return int(v) if isinstance(v, str) else v

    @field_validator("start_date", mode="before")
    @classmethod
    def _coerce_date(cls, v: object) -> object:
        return date_type.fromisoformat(v) if isinstance(v, str) else v


async def tp_list_training_plans() -> dict[str, Any]:
    """List the coach's authored training plans (slim)."""
    async with TPClient() as client:
        r = await client.get("/plans/v1/plans")
        if r.is_error:
            return _api_err(r)
        out = []
        for p in r.data or []:
            dur = p.get("trainingDurationByWeek") or []
            out.append({
                "plan_id": p.get("planId"),
                "title": (p.get("title") or "").strip(),
                "weeks": p.get("weekCount"),
                "workouts": p.get("workoutCount"),
                "total_hours": round(sum(dur), 1) if dur else None,
                "category": p.get("planCategory"),
                "price": p.get("price"),
                "is_public": p.get("isPublic"),
                "event_date": p.get("eventDate"),
            })
        return {"plans": out, "count": len(out)}


async def tp_get_training_plan(plan_id: int | str) -> dict[str, Any]:
    """Summary of one plan: weeks, per-week duration/distance, sport breakdown."""
    try:
        v = _PlanIdInput(plan_id=plan_id)  # type: ignore[arg-type]
    except (ValidationError, ValueError) as e:
        return _err("VALIDATION_ERROR",
                    format_validation_error(e) if isinstance(e, ValidationError) else str(e))
    async with TPClient() as client:
        r = await client.get(f"/plans/v1/plans/{v.plan_id}")
        if r.is_error:
            return _api_err(r)
        d = r.data or {}
        dur = d.get("trainingDurationByWeek") or []
        dist = d.get("trainingDistanceByWeek") or []
        by_sport = []
        for t in d.get("plannedWorkoutTypeDurations") or []:
            if (t.get("duration") or 0) or (t.get("distance") or 0):
                by_sport.append({
                    "sport": _SPORT_BY_TYPE.get(t.get("workoutTypeId"), str(t.get("workoutTypeId"))),
                    "hours": round(t.get("duration") or 0, 1),
                    "km": round((t.get("distance") or 0) / 1000, 1),
                })
        return {
            "plan_id": d.get("planId"),
            "title": (d.get("title") or "").strip(),
            "weeks": d.get("weekCount"),
            "day_count": d.get("dayCount"),
            "workouts": d.get("workoutCount"),
            "description": d.get("description"),
            "duration_by_week_h": [round(x, 2) for x in dur],
            "distance_by_week_km": [round(x / 1000, 1) for x in dist],
            "by_sport": by_sport,
            "start_date": (d.get("startDate") or "")[:10] or None,
        }


async def _fetch_plan_workouts(
    client: TPClient, plan_id: int,
) -> tuple[date_type | None, Any]:
    """(plan startDate, [workouts]) or (None, error_dict). The plan-workouts range
    endpoint is NOT 90-day-capped (verified on a 112-day plan)."""
    det = await client.get(f"/plans/v1/plans/{plan_id}")
    if det.is_error:
        return None, _api_err(det)
    d = det.data or {}
    start = (d.get("startDate") or "")[:10]
    days = d.get("dayCount") or (d.get("weekCount") or 0) * 7
    if not start or not days:
        return None, _err("API_ERROR", "Plan has no startDate/dayCount.")
    sd = date_type.fromisoformat(start)
    ed = sd + timedelta(days=int(days) + 1)
    wr = await client.get(f"/plans/v1/plans/{plan_id}/workouts/{sd.isoformat()}/{ed.isoformat()}")
    if wr.is_error:
        return None, _api_err(wr)
    return sd, (wr.data or [])


async def tp_get_training_plan_workouts(plan_id: int | str) -> dict[str, Any]:
    """All workouts of a plan, laid out by week/day (slim — title/description/
    duration/TSS/has_structure; full structure is omitted to keep the payload
    small, but is used internally by tp_apply_training_plan)."""
    try:
        v = _PlanIdInput(plan_id=plan_id)  # type: ignore[arg-type]
    except (ValidationError, ValueError) as e:
        return _err("VALIDATION_ERROR",
                    format_validation_error(e) if isinstance(e, ValidationError) else str(e))
    async with TPClient() as client:
        sd, ws = await _fetch_plan_workouts(client, v.plan_id)
        if sd is None:
            return ws  # error dict
        out = []
        for w in ws:
            wd = (w.get("workoutDay") or "")[:10]
            try:
                rel = (date_type.fromisoformat(wd) - sd).days + 1 if wd else None
            except ValueError:
                rel = None
            out.append({
                "week": ((rel - 1) // 7 + 1) if rel else None,
                "day": rel,
                "sport": _SPORT_BY_TYPE.get(w.get("workoutTypeValueId"), str(w.get("workoutTypeValueId"))),
                "title": (w.get("title") or "").strip(),
                "description": w.get("description"),
                "duration_min": round((w.get("totalTimePlanned") or 0) * 60) or None,
                "distance_km": round((w.get("distancePlanned") or 0) / 1000, 2) or None,
                "tss": w.get("tssPlanned"),
                "has_structure": w.get("structure") is not None,
            })
        out.sort(key=lambda x: (x["day"] or 0))
        result: dict[str, Any] = {
            "plan_id": v.plan_id, "workouts": out, "count": len(out),
        }

        # Notes are part of the Training Plan's relative-week calendar, but
        # TrainingPeaks exposes them via a DIFFERENT endpoint. Include them
        # in this already established read-only tool so a cached ChatGPT MCP
        # action list (which may hide newly added tools) can still audit the
        # plan end-to-end. A notes API error must not erase valid workouts.
        note_result = await tp_get_training_plan_notes(v.plan_id)
        if note_result.get("isError"):
            result["calendar_notes"] = None
            result["calendar_notes_status"] = "unavailable"
            result["calendar_notes_error"] = {
                "code": note_result.get("error_code", "API_ERROR"),
                "message": note_result.get("message", "Plan notes could not be read."),
            }
        else:
            result["calendar_notes"] = note_result.get("notes", [])
            result["calendar_notes_count"] = note_result.get("count", 0)
            result["calendar_notes_status"] = "ok"
        return result


# NB on the NATIVE apply command — fully reverse-engineered (Claude-in-Chrome HAR +
# live probes) but NOT used, because every server-side replication produced a
# DEGENERATE apply (an applied-plan record with endDate == startDate-ish and ZERO
# workouts materialised), and the body that makes the web's apply actually populate
# the calendar could not be reproduced:
#   1. POST /plans/v1/commands/applyplan  body=[{athleteId(str), planId, planTitle,
#      startType, targetDate}] → [{appliedPlanId, startDate, endDate, ...}].
#   2. Async job; drive it by polling POST /plans/v1/appliedplans/applyPlanStatus
#      with a BARE array body [appliedPlanId] (NOT {"AppliedPlanIds":[...]} — that
#      400s), response {"batchStatus": N}, 2 = complete.
# Live result: with startType 1 AND 2 the command returns batchStatus 2 (="done")
# yet creates NO workouts on the calendar (verified across several far-date applies
# on two athletes); startType 0 is rejected. The only captured web payload was a
# startType:1 apply that was itself degenerate, so the working-apply body is unknown.
# → We use the SYNTHETIC copy below: deterministic, one-shot, fully verified live.
# (Revisit native only with a HAR of a CONFIRMED-WORKING web apply's request body.)


async def tp_apply_training_plan(plan_id: int | str, start_date: str) -> dict[str, Any]:
    """Apply a plan to the athlete's calendar from ``start_date`` by copying each
    plan workout to ``start_date + relative_day`` (structure/description/TSS
    preserved); training-period annotation markers are skipped. Athlete is resolved
    from the coach's athlete_override context (the ``athlete`` arg, handled by the
    server dispatch)."""
    try:
        v = _ApplyInput(plan_id=plan_id, start_date=start_date)  # type: ignore[arg-type]
    except (ValidationError, ValueError) as e:
        return _err("VALIDATION_ERROR",
                    format_validation_error(e) if isinstance(e, ValidationError) else str(e))
    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return _err("AUTH_INVALID", "Could not get athlete ID. Re-authenticate.")

        # The synthetic copy method is still a pilot, NOT TrainingPeaks'
        # native linked-plan application. Never expose an unrestricted
        # calendar mutation path to actual coached athletes during the lab.
        pilot_start = date_type(2027, 6, 21)
        if (
            v.plan_id != 684206
            or v.start_date != pilot_start
            or str(athlete_id) != "941614"
        ):
            return _err(
                "PROTECTED_RESOURCE",
                "Pilot synthetic copy restricted to Training Plan 684206, "
                "Piattaforma TEST (941614), starting 2027-06-21.",
            )
        plan_response = await client.get(f"/plans/v1/plans/{v.plan_id}")
        if plan_response.is_error:
            return _api_err(plan_response)
        pilot_error = _test_plan_guard(plan_response.data or {})
        if pilot_error:
            return pilot_error

        sd, ws = await _fetch_plan_workouts(client, v.plan_id)
        if sd is None:
            return ws  # error dict

        # Require exactly the three pilot workouts in their expected order,
        # all on the first three days of the sandbox week; fail closed if a
        # partial/unexpected plan would be copied.
        expected = (
            (0, 1, "[MCP TEST] Swim | Tecnica 1200 m - Builder"),
            (1, 2, "[MCP TEST] Bike | 3x5' FTP controllato"),
            (2, 3, "[MCP TEST] Run | Progressivo RPE 35'"),
        )
        try:
            actual = sorted(
                (
                    (date_type.fromisoformat((w["workoutDay"] or "")[:10]) - sd).days,
                    w["workoutTypeValueId"],
                    (w["title"] or "").strip(),
                )
                for w in ws
            )
        except (KeyError, TypeError, ValueError):
            return _err("VALIDATION_ERROR", "Unexpected pilot-plan workout structure.")
        if actual != list(expected):
            return _err("PROTECTED_RESOURCE",
                        "Plan no longer matches the three approved lab workouts.")

        # A non-idempotent copy must not place duplicates or overwrite an
        # occupied sandbox. This is checked AGAIN by the caller's readback.
        sandbox_end = pilot_start + timedelta(days=6)
        occupied = await client.get(
            f"/fitness/v6/athletes/{athlete_id}/workouts/"
            f"{pilot_start.isoformat()}/{sandbox_end.isoformat()}"
        )
        if occupied.is_error:
            return _api_err(occupied)
        if not isinstance(occupied.data, list):
            return _err("API_ERROR", "Unexpected sandbox response; refusing to copy.")
        if occupied.data:
            return _err("ALREADY_EXISTS",
                        "Sandbox has existing workouts; refusing synthetic copy.")

        created = failed = skipped = 0
        first_error: str | None = None
        for w in ws:
            tid = w.get("workoutTypeValueId")
            if tid == _PERIOD_TYPE_ID:
                skipped += 1   # training-period annotation, not a session
                continue
            wd = (w.get("workoutDay") or "")[:10]
            try:
                rel = (date_type.fromisoformat(wd) - sd).days if wd else None
            except ValueError:
                rel = None
            if rel is None:
                failed += 1
                continue
            day = v.start_date + timedelta(days=rel)
            payload: dict[str, Any] = {
                "athleteId": athlete_id,
                "workoutDay": f"{day.isoformat()}T00:00:00",
                "workoutTypeFamilyId": tid,   # family == value for standard sports
                "workoutTypeValueId": tid,
                "title": (w.get("title") or "Workout").strip(),
            }
            if w.get("totalTimePlanned") is not None:
                payload["totalTimePlanned"] = w["totalTimePlanned"]
            if w.get("description"):
                payload["description"] = w["description"]
            if w.get("distancePlanned") is not None:
                payload["distancePlanned"] = w["distancePlanned"]
            if w.get("tssPlanned") is not None:
                payload["tssPlanned"] = w["tssPlanned"]
            if w.get("ifPlanned") is not None:
                payload["ifPlanned"] = w["ifPlanned"]
            st = w.get("structure")
            if isinstance(st, dict):
                payload["structure"] = json.dumps(st)

            resp = await client.post(f"/fitness/v6/athletes/{athlete_id}/workouts", json=payload)
            if resp.is_error:
                failed += 1
                if first_error is None:
                    first_error = resp.message
                # Stop at the first failure. The caller must audit partial
                # writes and never blindly retry a non-idempotent copy.
                break
            else:
                created += 1

        result: dict[str, Any] = {
            "success": failed == 0 and created > 0,
            "method": "synthetic",
            "plan_id": v.plan_id,
            "athlete_id": athlete_id,
            "start_date": v.start_date.isoformat(),
            "created": created,
            "failed": failed,
            "skipped_periods": skipped,
            "total": len(ws),
        }
        if first_error:
            result["first_error"] = first_error[:160]
        return result


# Experimental Training Plan Library write tools. These are deliberately
# restricted to private [MCP TEST] plans until the API behaviour is proven.
# TrainingPeaks plan-management endpoints are unofficial; creation requires
# live verification against the coach's own test plan before production use.


def _test_plan_guard(plan: dict[str, Any]) -> dict[str, Any] | None:
    title = (plan.get("title") or "").strip()
    if not title.startswith("[MCP TEST]"):
        return _err("PROTECTED_RESOURCE",
                    "Writes are limited to Training Plans starting with [MCP TEST].")
    if plan.get("isPublic") is True or plan.get("price") not in (None, 0):
        return _err("PROTECTED_RESOURCE",
                    "Refusing to write to a published or priced Training Plan.")
    return None


def _parse_plan_date(value: str) -> date_type | None:
    try:
        return date_type.fromisoformat(value)
    except (ValueError, TypeError):
        return None


async def tp_create_training_plan(
    title: str, start_date: str, week_count: int = 1,
    description: str | None = None,
) -> dict[str, Any]:
    """EXPERIMENTAL: create a private, minimal [MCP TEST] plan.

    Endpoint/body for plan creation still require a live provider readback.
    Never retries a POST after an ambiguous response.
    """
    if not title or not title.strip().startswith("[MCP TEST]"):
        return _err("VALIDATION_ERROR", "Only [MCP TEST] plans may be created.")
    if not isinstance(week_count, int) or isinstance(week_count, bool):
        return _err("VALIDATION_ERROR", "week_count must be an integer.")
    start = _parse_plan_date(start_date)
    if start is None or start.weekday() != 0:
        return _err("VALIDATION_ERROR", "start_date must be a Monday (YYYY-MM-DD).")
    if week_count == _INTERMEDIATE_PILOT_WEEKS:
        if title.strip() != _INTERMEDIATE_PILOT_TITLE or start != _INTERMEDIATE_PILOT_START:
            return _err(
                "PROTECTED_RESOURCE",
                "24-week plan creation is limited to the exact private Intermediate pilot.",
            )
    elif not 1 <= week_count <= 2:
        return _err(
            "VALIDATION_ERROR",
            "Other lab plans must be 1 or 2 weeks; the approved pilot is exactly 24.",
        )

    async with TPClient() as client:
        before = await client.get("/plans/v1/plans")
        if before.is_error:
            return _api_err(before)
        if any((p.get("title") or "").strip() == title.strip()
               for p in (before.data or [])):
            return _err("ALREADY_EXISTS",
                        "A plan with this exact title already exists. Refusing duplicate creation.")

        payload: dict[str, Any] = {
            "title": title.strip(),
            "startDate": f"{start.isoformat()}T00:00:00",
            "weekCount": week_count,
            "dayCount": week_count * 7,
            "isPublic": False,
        }
        if description is not None:
            payload["description"] = description

        # Unlike the workout-library command, the Training Plan creation body
        # is not yet captured from a confirmed browser request. This is a single
        # guarded candidate endpoint, not a verified TP API contract.
        created = await client.post("/plans/v1/plans", json=payload)
        if created.is_error:
            return _api_err(created)

        value = created.data if isinstance(created.data, dict) else {}
        plan_id = value.get("planId") or value.get("id")
        if plan_id is None:
            after = await client.get("/plans/v1/plans")
            if after.is_error:
                return _err("WRITE_UNVERIFIED",
                            "POST accepted but listing failed; check existing plans before retrying.")
            candidates = [p for p in (after.data or [])
                          if (p.get("title") or "").strip() == title.strip()]
            if len(candidates) != 1 or not candidates[0].get("planId"):
                return _err("WRITE_UNVERIFIED",
                            "Creation not uniquely verified; inspect plan library before retrying.")
            plan_id = candidates[0]["planId"]

        verified = await client.get(f"/plans/v1/plans/{plan_id}")
        if verified.is_error:
            return _err("WRITE_UNVERIFIED",
                        f"Plan {plan_id} returned by create but readback failed.")
        d = verified.data or {}
        if (d.get("title") or "").strip() != title.strip():
            return _err("WRITE_UNVERIFIED",
                        f"Plan {plan_id} readback does not match the intended title.")
        if d.get("isPublic") is True or d.get("price") not in (None, 0):
            return _err("PROTECTED_RESOURCE",
                        f"Plan {plan_id} is not confirmed private and unpriced; stop.")
        return {
            "success": True, "plan_id": plan_id,
            "title": title.strip(), "start_date": start.isoformat(),
            "weeks": week_count, "requested_weeks": week_count,
            "provider_observed_weeks": d.get("weekCount"),
            "provider_observed_start_date": (d.get("startDate") or "")[:10] or None,
            "calendar_bootstrap_pending": not bool(d.get("startDate")),
            "is_public": d.get("isPublic", False),
            "verified": True,  # identity/private status only, not 24 populated weeks
        }


async def _get_writable_test_plan(
    client: TPClient, plan_id: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    result = await client.get(f"/plans/v1/plans/{plan_id}")
    if result.is_error:
        return None, _api_err(result)
    d = result.data or {}
    guard = _test_plan_guard(d)
    if guard:
        return None, guard
    return d, None


def _check_plan_date(
    plan: dict[str, Any], workout_date: str, *,
    allow_first_workout_bootstrap: bool = False,
    bootstrap_item_name: str | None = None,
) -> dict[str, Any] | None:
    target = _parse_plan_date(workout_date)
    start = _parse_plan_date((plan.get("startDate") or "")[:10])
    if target is None:
        return _err("VALIDATION_ERROR", "Invalid plan calendar date.")

    title = (plan.get("title") or "").strip()
    # A newly created Standard Training Plan may expose zero weeks until its
    # first workout. Never let a Tuesday bootstrap shift week 1 from Monday.
    if title == _INTERMEDIATE_PILOT_TITLE:
        if not (
            _INTERMEDIATE_PILOT_START <= target
            < _INTERMEDIATE_PILOT_START + timedelta(weeks=_INTERMEDIATE_PILOT_WEEKS)
        ):
            return _err("PROTECTED_RESOURCE", "Date outside the Intermediate pilot.")
        if start is not None and start != _INTERMEDIATE_PILOT_START:
            return _err(
                "PROTECTED_RESOURCE",
                "Intermediate pilot has a shifted startDate: stop and inspect.",
            )
        if start is None:
            if (
                allow_first_workout_bootstrap
                and plan.get("workoutCount") in (None, 0)
                and target == _INTERMEDIATE_PILOT_START
                and (bootstrap_item_name or "").startswith(
                    "[MCP TEST] " + _INTERMEDIATE_PILOT_FIRST_UID + " | "
                )
            ):
                return None
            return _err(
                "PROTECTED_RESOURCE",
                "Only W1 Monday's weekly-objective item may "
                "bootstrap this empty 24-week pilot.",
            )
        # Subsequent weeks may be empty even though TP reports weekCount=1;
        # the exact title/first-date guard constrains this one development plan.
        return None

    # Preserve the existing 3-workout experiment without broadening its scope.
    days = max(plan.get("dayCount") or 0, (plan.get("weekCount") or 0) * 7)
    if start is None or not isinstance(days, int) or days <= 0:
        if (
            allow_first_workout_bootstrap
            and plan.get("planId") == 684206
            and title == "[MCP TEST] Training Plan — Swim Bike Run"
            and plan.get("workoutCount") in (None, 0)
            and target == date_type(2027, 6, 21)
        ):
            return None
        return _err(
            "VALIDATION_ERROR",
            "Plan has no calendar range; only the guarded pilot "
            "bootstrap workout is permitted.",
        )
    if not start <= target < start + timedelta(days=days):
        return _err(
            "VALIDATION_ERROR",
            "Target day must fall inside the [MCP TEST] plan date range.",
        )
    return None

async def tp_add_training_plan_library_workout(
    plan_id: int | str, library_id: str, item_id: str, workout_date: str,
) -> dict[str, Any]:
    """Add one existing [MCP TEST] workout template to one [MCP TEST] plan.

    Provider endpoint/body documented from a coach account. Does not apply the
    plan to any athlete or modify a library template.
    """
    try:
        v = _PlanIdInput(plan_id=plan_id)  # type: ignore[arg-type]
        lib_id, template_id = int(library_id), int(item_id)
        if lib_id <= 0 or template_id <= 0:
            raise ValueError("IDs must be positive")
    except (ValidationError, ValueError, TypeError) as e:
        return _err("VALIDATION_ERROR", str(e))
    async with TPClient() as client:
        plan, error = await _get_writable_test_plan(client, v.plan_id)
        if error is not None:
            return error
        assert plan is not None
        is_archive_pilot = (plan.get("title") or "").strip() == _INTERMEDIATE_PILOT_TITLE
        # Keep the existing simple-plan guard order stable, including its
        # fail-closed behavior before a Workout Library GET.
        if not is_archive_pilot:
            date_error = _check_plan_date(
                plan, workout_date,
                allow_first_workout_bootstrap=(
                    v.plan_id == 684206 and lib_id == 3890637
                    and template_id == 14935065
                ),
            )
            if date_error:
                return date_error
        # Validate the actual template BEFORE permitting an empty-plan
        # bootstrap. Never let an unrelated workout anchor the new calendar.
        library = await client.get(f"/exerciselibrary/v2/libraries/{lib_id}/items")
        if library.is_error:
            return _api_err(library)
        if not isinstance(library.data, list):
            return _err("API_ERROR", "Unverified Workout Library response.")
        candidate = next(
            (item for item in library.data
             if item.get("exerciseLibraryItemId") == template_id), None,
        )
        if candidate is None or not (candidate.get("itemName") or "").startswith("[MCP TEST]"):
            return _err(
                "PROTECTED_RESOURCE",
                "Only existing [MCP TEST] library items can be inserted.",
            )
        if (plan.get("title") or "").strip() == _INTERMEDIATE_PILOT_TITLE:
            if not (candidate.get("itemName") or "").startswith("[MCP TEST] IMINT24W-"):
                return _err(
                    "PROTECTED_RESOURCE",
                    "Intermediate pilot requires a canonical UID-prefixed template.",
                )
        if is_archive_pilot:
            date_error = _check_plan_date(
                plan, workout_date, allow_first_workout_bootstrap=True,
                bootstrap_item_name=candidate.get("itemName"),
            )
            if date_error:
                return date_error

        # The endpoint is non-idempotent: check whether the same template
        # was already copied to this exact plan day before posting.
        first = (plan.get("startDate") or "")[:10]
        if first:
            if is_archive_pilot:
                # Source metadata can lag behind a partially populated
                # 24-week pilot. Check the EXACT target day regardless of the
                # provider's currently observed weekCount/dayCount.
                start = date_type.fromisoformat(workout_date)
                end = start + timedelta(days=2)
            else:
                start = date_type.fromisoformat(first)
                length = max(plan.get("dayCount") or 0,
                             (plan.get("weekCount") or 0) * 7)
                end = start + timedelta(days=length + 1)
            existing = await client.get(
                f"/plans/v1/plans/{v.plan_id}/workouts/"
                f"{start.isoformat()}/{end.isoformat()}"
            )
            if existing.is_error:
                return _api_err(existing)
            for workout in existing.data or []:
                workout_day = (workout.get("workoutDay") or "")[:10]
                if (workout_day == workout_date
                    and (workout.get("title") or "").strip()
                        == (candidate.get("itemName") or "").strip()):
                    return _err("ALREADY_EXISTS",
                                "This [MCP TEST] library workout already exists "
                                "on this plan day. Refusing a duplicate.")

        payload = {
            "planId": v.plan_id,
            "exerciseLibraryItemId": template_id,
            "workoutDateTime": workout_date,
        }
        r = await client.post(
            f"/plans/v1/plans/{v.plan_id}/commands/addworkoutfromlibraryitem",
            json=payload,
        )
        if r.is_error:
            return _api_err(r)
        return {
            "success": True, "plan_id": v.plan_id, "library_id": lib_id,
            "item_id": template_id, "workout_date": workout_date,
            "provider_acknowledged": True,
            "readback_required": True,
        }



async def tp_get_training_plan_notes(plan_id: int | str) -> dict[str, Any]:
    """Read calendar notes from a Training Plan's relative-week calendar.

    TrainingPeaks uses GET /plans/v1/plans/{id}/calendarNote/{start}/{end};
    reading these notes is separate from workout comments and athlete notes.
    """
    try:
        v = _PlanIdInput(plan_id=plan_id)  # type: ignore[arg-type]
    except (ValidationError, ValueError) as e:
        return _err("VALIDATION_ERROR", str(e))
    async with TPClient() as client:
        detail = await client.get(f"/plans/v1/plans/{v.plan_id}")
        if detail.is_error:
            return _api_err(detail)
        plan = detail.data or {}
        start = _parse_plan_date((plan.get("startDate") or "")[:10])
        days = max(plan.get("dayCount") or 0,
                   (plan.get("weekCount") or 0) * 7)
        if start is None or days <= 0:
            return _err("API_ERROR", "Plan has no populated calendar range.")
        end = start + timedelta(days=days + 1)
        response = await client.get(
            f"/plans/v1/plans/{v.plan_id}/calendarNote/"
            f"{start.isoformat()}/{end.isoformat()}"
        )
        if response.is_error:
            return _api_err(response)
        # Do not mistake an undocumented response wrapper or partial
        # provider failure for a successfully verified empty notes list.
        if not isinstance(response.data, list) or any(
            not isinstance(note, dict) for note in response.data
        ):
            return _err("API_ERROR", "Unexpected native Training Plan notes payload.")
        out = []
        for note in response.data:
            day = (note.get("noteDate") or note.get("date") or "")[:10]
            offset = None
            try:
                offset = (date_type.fromisoformat(day) - start).days + 1
            except ValueError:
                pass
            out.append({
                "note_id": note.get("id") or note.get("calendarNoteId")
                          or note.get("noteId"),
                "title": (note.get("title") or "").strip(),
                "description": note.get("description"),
                "date": day or None,
                "week": (offset - 1) // 7 + 1 if offset else None,
                "day": offset,
            })
        return {"plan_id": v.plan_id, "notes": out, "count": len(out)}

async def tp_add_training_plan_note(
    plan_id: int | str, note_date: str, title: str, description: str,
) -> dict[str, Any]:
    """Add one calendar note to a private [MCP TEST] Training Plan only."""
    try:
        v = _PlanIdInput(plan_id=plan_id)  # type: ignore[arg-type]
    except (ValidationError, ValueError) as e:
        return _err("VALIDATION_ERROR", str(e))
    if not title.strip().startswith("[MCP TEST]"):
        return _err("VALIDATION_ERROR", "Test note title must begin with [MCP TEST].")
    async with TPClient() as client:
        plan, error = await _get_writable_test_plan(client, v.plan_id)
        if error is not None:
            return error
        assert plan is not None
        date_error = _check_plan_date(plan, note_date)
        if date_error:
            return date_error
        target = date_type.fromisoformat(note_date)
        start = date_type.fromisoformat(plan["startDate"][:10])
        week = (target - start).days // 7 + 1
        # This POST is non-idempotent. Preflight the exact plan calendar
        # before creating the note, and never retry an ambiguous POST.
        full_span = max(plan.get("dayCount") or 0,
                        (plan.get("weekCount") or 0) * 7)
        end = start + timedelta(days=full_span + 1)
        existing = await client.get(
            f"/plans/v1/plans/{v.plan_id}/calendarNote/"
            f"{start.isoformat()}/{end.isoformat()}"
        )
        if existing.is_error:
            return _api_err(existing)
        if not isinstance(existing.data, list):
            return _err("API_ERROR",
                        "Unexpected Training Plan notes response; refusing an unverified POST.")
        if any(
            (n.get("title") or "").strip() == title.strip()
            and ((n.get("noteDate") or n.get("date") or "")[:10] == note_date)
            for n in existing.data
        ):
            return _err("ALREADY_EXISTS",
                        "A note with this exact title already exists on this plan day.")
        payload = {
            "planId": v.plan_id, "title": title.strip(),
            "noteDate": note_date, "description": description,
            "attachments": [],
            "standardFormatDate": f"Week {week}, {target.strftime('%A')}",
        }
        r = await client.post(f"/plans/v1/plans/{v.plan_id}/calendarNote", json=payload)
        if r.is_error:
            return _api_err(r)
        return {
            "success": True, "plan_id": v.plan_id,
            "title": title.strip(), "date": note_date,
            "provider_acknowledged": True, "readback_required": True,
        }
