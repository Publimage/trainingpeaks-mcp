#!/usr/bin/env python3
"""Live READ-ONLY preview for Intermediate test Training Plan 684602.

Rebind all historical canonical UIDs to CURRENT provider workout IDs before
offering any diff. Never trust old IDs in the historical release manifest.
No provider writes in this file.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from field_edits import Edit, Record, ScopeError, preview, normalize_sport

PLAN_ID = 684602
EXPECTED_TITLE = "[MCP TEST] IRONMAN Intermediate Assembly 24W"
MONDAY = date(2026, 10, 5)
END = date(2027, 3, 30)
SPORT_ID = {"swimming": 1, "cycling": 2, "running": 3}
DATA = Path(__file__).resolve().parents[1] / "data"


def require(value: bool, message: str) -> None:
    if not value:
        raise ScopeError(message)


def provider_id(obj: dict[str, Any], keys: tuple[str, ...]) -> int:
    values = [obj[k] for k in keys if type(obj.get(k)) is int and obj[k] > 0]
    require(bool(values) and len(set(values)) == 1, "Missing or ambiguous native provider ID")
    return values[0]


def day(obj: dict[str, Any]) -> str:
    return str(obj.get("workoutDay") or obj.get("noteDate") or obj.get("date") or "")[:10]


def check_plan(plan: Any) -> None:
    require(isinstance(plan, dict), "Plan response is not a native object")
    require(plan.get("planId") == PLAN_ID and plan.get("title") == EXPECTED_TITLE,
            "Plan identity changed")
    require(plan.get("isPublic") is False and plan.get("price") in (None, 0),
            "Refusing a public/priced plan")
    require(plan.get("weekCount") == 24 and plan.get("workoutCount") == 259,
            "Plan expected 24 weeks and exactly 259 workouts")


def bind_workouts(manifest: list[dict], native: list[dict]) -> list[Record]:
    require(len(manifest) == 229 and len(native) == 229, "Expected 229 canonical and native endurance entries")
    found: set[int] = set()
    records: list[Record] = []
    for source in manifest:
        sport = normalize_sport(str(source["sport"]))
        date_str = (MONDAY + timedelta(days=int(source["day"]) - 1)).isoformat()
        candidates = [
            item for item in native
            if day(item) == date_str and item.get("workoutTypeValueId") == SPORT_ID[sport]
            and item.get("title") == source["title_after"]
            and len(item.get("description") or "") == source["description_length"]
        ]
        require(len(candidates) == 1, "Cannot uniquely reconcile " + source["canonical_uid"])
        item = candidates[0]
        new_id = provider_id(item, ("workoutId", "planWorkoutId", "id"))
        require(new_id not in found, "Repeated native ID in reconciled workouts")
        found.add(new_id)
        records.append(Record(
            uid=source["canonical_uid"], resource="training_plan_workout",
            week=int(source["week"]), sport=sport, provider_id=new_id,
            locale="it-IT",
            fields={"title": item["title"], "description": item.get("description") or ""},
        ))
    require(len(found) == 229, "Unmatched native workout(s)")
    return records


def bind_notes(manifest: list[dict], native: list[dict]) -> list[Record]:
    require(len(manifest) == 35 and len(native) == 35, "Expected 35 canonical and native notes")
    index = {provider_id(n, ("id", "calendarNoteId", "noteId")): n for n in native}
    require(len(index) == 35, "Duplicate provider notes")
    records: list[Record] = []
    for source in manifest:
        item = index.get(source["note_id"])
        require(item is not None and item.get("title") == source["title_after"],
                "Note title/ID mismatch " + source["uid"])
        require(day(item) == source["date"] and item.get("description") == source["description"],
                "Note content/date mismatch " + source["uid"])
        records.append(Record(
            uid=source["uid"], resource="training_plan_note", week=int(source["week"]),
            sport="other", provider_id=source["note_id"], locale="it-IT",
            fields={"title": item["title"], "description": item["description"]},
        ))
    return records


async def live_records(target: str, manifest_directory: Path) -> list[Record]:
    from tp_mcp.client import TPClient
    async with TPClient() as client:
        plan = await client.get(f"/plans/v1/plans/{PLAN_ID}")
        require(not plan.is_error, "Plan GET failed")
        check_plan(plan.data)
        section = "workouts" if target == "workouts" else "calendarNote"
        native = await client.get(
            f"/plans/v1/plans/{PLAN_ID}/{section}/{MONDAY.isoformat()}/{END.isoformat()}"
        )
        require(not native.is_error and isinstance(native.data, list),
                "Native " + section + " GET failed")
    filename = ("intermediate_plan_title_release_manifest.json" if target == "workouts"
                else "intermediate_notes_release_manifest.json")
    data = json.loads((manifest_directory / filename).read_text(encoding="utf-8"))
    require(data.get("plan_id", PLAN_ID) == PLAN_ID, "Wrong manifest plan ID")
    return (bind_workouts(data["workouts"], native.data) if target == "workouts"
            else bind_notes(data["provider_notes_to_clean"], native.data))


async def run(args: argparse.Namespace) -> dict:
    records = await live_records(args.target, args.manifest_dir)
    outcome = preview(
        records,
        resource="training_plan_workout" if args.target == "workouts" else "training_plan_note",
        locale="it-IT", expected_count=args.expected_count,
        edit=Edit(field=args.field, operation=args.operation, text=args.text, find=args.find),
        sports=args.sport, weeks=args.week, uids=args.uid,
    )
    outcome.update({"plan_id": PLAN_ID, "verified_live": True, "provider_writes": 0})
    return outcome


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", choices=["workouts", "notes"], required=True)
    p.add_argument("--field", choices=["title", "description"], required=True)
    p.add_argument("--operation", choices=["set", "prepend", "append", "replace_text",
                                           "remove_prefix", "remove_suffix"], required=True)
    p.add_argument("--text", default="")
    p.add_argument("--find", default="")
    p.add_argument("--sport", action="append")
    p.add_argument("--week", action="append", type=int)
    p.add_argument("--uid", action="append")
    p.add_argument("--expected-count", type=int, required=True)
    p.add_argument("--manifest-dir", type=Path, default=DATA)
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    try:
        result = asyncio.run(run(args))
        if args.out:
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "diffs"},
                         ensure_ascii=False, indent=2))
        for item in result["diffs"][:3]:
            print(json.dumps({k: item[k] for k in ("uid", "provider_id", "field", "before", "after")},
                             ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({"stage": "STOP", "reason": str(e)[:350], "provider_writes": 0},
                         ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
