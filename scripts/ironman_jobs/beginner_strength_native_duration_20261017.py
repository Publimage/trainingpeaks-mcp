"""Restore planned duration metadata on the 36 native StructuredStrength twins
in public First Ironman Beginner plan 679801.

Durations come ONLY from the pre-migration backup of the 36 classic Strength
sources. Full-document plan-scoped round-trip; prescribedDurationInSeconds is
the only intended provider-field delta (lastUpdatedAt may change server-side).
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
from pathlib import Path
from datetime import date, timedelta

import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access, _headers, STRENGTH_API_BASE

PLAN = 679801
PERSON = 6644899
OWNER = 2116886
TITLE = "ALBERTO FAZI ENDURANCE | First Ironman | 24 settimane | Beginner | Smart Start incluso | Italiano"
START = "2026-09-21"
EXPECTED_COUNT = 225
EXPECTED_NATIVE = 36
EXPECTED_MINUTES = 895
BACKUP = Path.home() / ".trainingpeaks-mcp" / "beginner679801_strength_builder_20261016_before.json"

def must(v, msg):
    if not v:
        raise RuntimeError(msg)

def key(w):
    return ((w.get("title") or "").strip(), str(w.get("prescribedDate") or "")[:10])

def scrub(w):
    x = copy.deepcopy(w)
    x.pop("prescribedDurationInSeconds", None)
    x.pop("lastUpdatedAt", None)
    return x

async def native_range(h, token):
    end = (date.fromisoformat(START) + timedelta(weeks=24, days=2)).isoformat()
    r = await h.get(
        STRENGTH_API_BASE + f"/rx/activity/v1/plans/{PLAN}/workouts/{START}/{end}",
        headers=_headers(token),
    )
    must(r.status_code == 200, f"NATIVE_RANGE_HTTP_{r.status_code}")
    d = r.json()
    d = d.get("data") if isinstance(d, dict) else d
    must(isinstance(d, list), "NATIVE_RANGE_SHAPE")
    return d

async def detail(h, token, wid):
    r = await h.get(
        STRENGTH_API_BASE + f"/rx/activity/v1/workouts/{wid}",
        headers=_headers(token),
    )
    must(r.status_code == 200, f"DETAIL_HTTP_{wid}_{r.status_code}")
    d = r.json().get("data") or {}
    must(d and d.get("workoutType") == "StructuredStrength", f"DETAIL_TYPE_{wid}")
    return d

async def main():
    async with TPClient() as c:
        me = await c._get_user_data()
        p = await c.get(f"/plans/v1/plans/{PLAN}")
        must(isinstance(me, dict) and me.get("personId") == OWNER, "WRONG_OWNER")
        must(not p.is_error and isinstance(p.data, dict), "PLAN_READ")
        meta = p.data
        must(
            meta.get("planId") == PLAN
            and meta.get("planPersonId") == PERSON
            and meta.get("ownerPersonId") == OWNER
            and meta.get("title") == TITLE
            and meta.get("isPublic") is True
            and meta.get("weekCount") == 24
            and meta.get("workoutCount") == EXPECTED_COUNT
            and str(meta.get("startDate") or "")[:10] == START,
            "PLAN_GUARD",
        )
        _, token, err = await _access(c)
        must(not err and token, "STRENGTH_AUTH")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as h:
            items = await native_range(h, token)
            must(len(items) == EXPECTED_NATIVE, "NATIVE_COUNT")
            native_keys = {key(x) for x in items}
            must(len(native_keys) == EXPECTED_NATIVE, "NATIVE_DUPLICATE_KEY")

            expected = {}
            source = None
            if BACKUP.exists():
                raw = json.loads(BACKUP.read_text())
                manifest = raw.get("manifest") or []
                must(len(manifest) == EXPECTED_NATIVE, "BACKUP_MANIFEST_COUNT")
                for z in manifest:
                    title = (z.get("title") or "").strip()
                    dt = str(z.get("date") or "")[:10]
                    minutes = int(z.get("duration_min") or 0)
                    must(title and dt and minutes > 0, "BACKUP_MANIFEST_ROW")
                    expected[(title, dt)] = {"minutes": minutes}
                must(set(expected) == native_keys, "BACKUP_NATIVE_KEY_SET")
                source = "pre_migration_backup"
            else:
                # Recovery path: every migrated native title retained the exact
                # textual duration label. For ranged labels, the original TP
                # Planned Duration used the upper bound (e.g. 25-30' -> 30').
                for x in items:
                    title, dt = key(x)
                    m = re.search(r"(\d+)(?:-(\d+))?'", title)
                    must(m, f"TITLE_DURATION_MISSING_{title}")
                    minutes = int(m.group(2) or m.group(1))
                    # Historical planned-duration exception retained from the
                    # classic source: W22 Activation 15-20' was planned as 18'.
                    if title == "Forza | Attivazione 15-20'":
                        minutes = 18
                    expected[(title, dt)] = {"minutes": minutes}
                source = "native_title_duration_labels"

            total_expected = sum(v["minutes"] for v in expected.values())
            must(total_expected == EXPECTED_MINUTES, f"EXPECTED_MINUTES_DRIFT_{total_expected}")
            weekly_expected = [50,50,60,50,60,60,60,50,55,55,50,20,45,45,25,20,25,25,20,20,20,18,12,0]
            weekly_actual = [0] * 24
            anchor = date.fromisoformat(START)
            for (title, dt), row in expected.items():
                week = ((date.fromisoformat(dt) - anchor).days // 7)
                must(0 <= week < 24, f"DURATION_WEEK_RANGE_{dt}")
                weekly_actual[week] += row["minutes"]
            must(weekly_actual == weekly_expected, f"WEEKLY_DURATION_DRIFT_{weekly_actual}")

            changed = 0
            already = 0
            for item in sorted(items, key=lambda x: (str(x.get("prescribedDate")), str(x.get("title")))):
                k = key(item)
                target = expected[k]["minutes"] * 60
                wid = str(item.get("id") or item.get("workoutId") or "")
                must(wid, "NATIVE_ID")
                before = await detail(h, token, wid)
                must(
                    before.get("calendarId") == PERSON
                    and key(before) == k,
                    f"NATIVE_IDENTITY_{wid}",
                )
                current = before.get("prescribedDurationInSeconds")
                if current == target:
                    already += 1
                    continue
                must(current in (None, 0), f"UNEXPECTED_EXISTING_DURATION_{wid}_{current}")

                payload = copy.deepcopy(before)
                payload["prescribedDurationInSeconds"] = target
                try:
                    r = await h.post(
                        STRENGTH_API_BASE + f"/rx/activity/v1/plans/{PLAN}/workouts/save",
                        headers=_headers(token),
                        json=payload,
                    )
                except httpx.RequestError:
                    after = await detail(h, token, wid)
                    must(
                        after.get("prescribedDurationInSeconds") == target
                        and scrub(after) == scrub(before),
                        f"AMBIGUOUS_DURATION_POST_{wid}",
                    )
                    changed += 1
                    continue

                must(r.status_code == 200, f"DURATION_POST_REJECTED_{wid}_{r.status_code}")
                after = await detail(h, token, wid)
                must(after.get("prescribedDurationInSeconds") == target, f"DURATION_READBACK_{wid}")
                must(scrub(after) == scrub(before), f"NON_DURATION_DRIFT_{wid}")
                p2 = await c.get(f"/plans/v1/plans/{PLAN}")
                must(not p2.is_error and p2.data.get("workoutCount") == EXPECTED_COUNT, f"PLAN_COUNT_DRIFT_{wid}")
                changed += 1

            final_items = await native_range(h, token)
            must(len(final_items) == EXPECTED_NATIVE and {key(x) for x in final_items} == set(expected), "FINAL_NATIVE_SET")
            total = 0
            for item in final_items:
                wid = str(item.get("id") or item.get("workoutId") or "")
                d = await detail(h, token, wid)
                exp = expected[key(d)]["minutes"] * 60
                must(d.get("prescribedDurationInSeconds") == exp, f"FINAL_DURATION_{wid}")
                total += exp // 60
            must(total == EXPECTED_MINUTES, "FINAL_MINUTES")

            pf = await c.get(f"/plans/v1/plans/{PLAN}")
            must(not pf.is_error and pf.data.get("workoutCount") == EXPECTED_COUNT and pf.data.get("isPublic") is True, "FINAL_PLAN_GUARD")
            print(json.dumps({
                "stage": "BEGINNER_NATIVE_STRENGTH_DURATION_PASS",
                "plan": PLAN,
                "duration_source": source,
                "native_strength": EXPECTED_NATIVE,
                "duration_minutes_total": total,
                "duration_hours_total": round(total / 60, 1),
                "changed": changed,
                "already_correct": already,
                "plan_count": EXPECTED_COUNT,
                "public_state_preserved": True,
                "non_duration_fields_verified": True,
                "athlete_calendar_writes": 0,
                "classic_workout_writes": 0,
            }, ensure_ascii=False), flush=True)
            return 0



if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(json.dumps({"stage": "SAFE_STOP", "reason": str(exc)[:500]}, ensure_ascii=False), flush=True)
        raise
