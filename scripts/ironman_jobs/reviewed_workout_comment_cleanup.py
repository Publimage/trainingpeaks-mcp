"""Reviewed, idempotent cleanup of specific coach-authored workout comments.

A checked-in manifest specifies exact athlete/workout/comment IDs. No arbitrary
tool arguments, no workout DELETE, no workout PUT, no other athlete writes.
The script can be reused with a separately reviewed manifest revision.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from tp_mcp.client import TPClient

OWNER = 2116886
ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/ironman_reviewed_workout_comment_cleanup.json"
MARKER = "VIDEO ESERCIZI TECNICI (link apribili dai commenti)"


class SafeStop(Exception):
    pass


def must(value: bool, message: str) -> None:
    if not value:
        raise SafeStop(message)


def read_manifest() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    must(manifest.get("schema") == "IRONMAN_REVIEWED_WORKOUT_COMMENT_CLEANUP_V1", "SCHEMA_MISMATCH")
    must(manifest.get("owner_id") == OWNER, "OWNER_SCOPE_MISMATCH")
    must(isinstance(manifest.get("athlete_id"), int) and manifest["athlete_id"] > 0, "ATHLETE_INVALID")
    must(manifest.get("expected_marker") == MARKER, "MARKER_MISMATCH")
    entries = manifest.get("entries")
    must(isinstance(entries, list) and 0 < len(entries) <= 10, "ENTRY_COUNT_INVALID")
    ids = set()
    for entry in entries:
        must(isinstance(entry, dict), "ENTRY_TYPE")
        wid, cid = entry.get("workout_id"), entry.get("comment_id")
        must(type(wid) is int and wid > 0 and type(cid) is int and cid > 0, "ENTRY_IDS")
        must((wid, cid) not in ids, "DUPLICATE_ENTRY")
        ids.add((wid, cid))
        urls = entry.get("expected_urls")
        must(isinstance(urls, list) and 1 <= len(urls) <= 4
             and all(isinstance(u, str) and u.startswith("https://youtu.be/") for u in urls),
             "URLS_INVALID")
    return manifest


def choose_comment(workout: dict, entry: dict) -> dict | None:
    """Refuse every deletion unless id, owner, body marker and URLs match."""
    wid, cid = entry["workout_id"], entry["comment_id"]
    must(isinstance(workout, dict), "WORKOUT_NOT_DICT")
    actual_wid = workout.get("workoutId", workout.get("id"))
    must(str(actual_wid) == str(wid), f"WORKOUT_ID_DRIFT:{wid}")
    description = workout.get("description")
    must(isinstance(description, str) and
         not description.startswith("VIDEO ESERCIZI | APRI I VIDEO"), f"DESCRIPTION_LAYOUT_DRIFT:{wid}")
    for url in entry["expected_urls"]:
        must(description.count(url) == 1 and f"Video:\n{url}" in description,
             f"INLINE_VIDEO_MISSING:{wid}")
    comments = workout.get("workoutComments") or []
    must(isinstance(comments, list), f"COMMENTS_NOT_LIST:{wid}")
    matches = [c for c in comments if isinstance(c, dict) and str(c.get("id")) == str(cid)]
    must(len(matches) <= 1, f"COMMENT_ID_DUPLICATE:{wid}")
    if not matches:
        return None
    comment = matches[0]
    must(str(comment.get("workoutId")) == str(wid), f"COMMENT_WORKOUT_MISMATCH:{wid}")
    must(str(comment.get("commenterPersonId")) == str(OWNER), f"NOT_OWN_COMMENT:{wid}")
    body = comment.get("comment")
    must(isinstance(body, str) and body.startswith(MARKER), f"COMMENT_BODY_DRIFT:{wid}")
    must(all(url in body for url in entry["expected_urls"]), f"COMMENT_URL_DRIFT:{wid}")
    return comment


async def get_workout(client: TPClient, athlete_id: int, workout_id: int) -> dict:
    r = await client.get(f"/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}")
    must(not r.is_error and isinstance(r.data, dict), f"WORKOUT_READ_FAILED:{workout_id}")
    return r.data


def stable_fields(workout: dict) -> dict:
    return {key: workout.get(key) for key in (
        "workoutId", "title", "description", "structure",
        "totalTimePlanned", "distancePlanned", "tssPlanned", "ifPlanned",
        "startTimePlanned", "isCompleted", "workoutType",
    )}


async def run() -> int:
    m = read_manifest()
    athlete_id = m["athlete_id"]
    async with TPClient() as client:
        identity = await client._get_user_data()
        must(isinstance(identity, dict) and str(identity.get("personId")) == str(OWNER),
             "AUTHENTICATED_OWNER_MISMATCH")

        # Entire-batch preflight before the first irreversible action.
        checks = []
        for entry in m["entries"]:
            workout = await get_workout(client, athlete_id, entry["workout_id"])
            match = choose_comment(workout, entry)
            all_ids = [str(c.get("id")) for c in workout.get("workoutComments") or []
                       if isinstance(c, dict)]
            checks.append((entry, match, stable_fields(workout), all_ids))
        print(json.dumps({
            "stage": "PREFLIGHT_VERIFIED", "athlete_id": athlete_id,
            "exact_targets": len(checks),
            "present_count": sum(match is not None for _, match, _, _ in checks),
        }), flush=True)

        deleted = 0
        for entry, match, original, before_ids in checks:
            wid, cid = entry["workout_id"], entry["comment_id"]
            if match is None:
                continue
            endpoint = f"/fitness/v2/athletes/{athlete_id}/workouts/{wid}/comments/{cid}"
            response = await client._request("DELETE", endpoint, _retry_on_401=False)
            current = await get_workout(client, athlete_id, wid)
            # An uncertain transport result may still have deleted the intended comment.
            after_ids = [str(c.get("id")) for c in current.get("workoutComments") or []
                         if isinstance(c, dict)]
            expected_ids = [x for x in before_ids if x != str(cid)]
            must(after_ids == expected_ids, f"COMMENT_DELETE_READBACK_FAILED:{wid}:{cid}")
            must(stable_fields(current) == original, f"WORKOUT_CHANGED:{wid}")
            must(choose_comment(current, entry) is None, f"COMMENT_STILL_PRESENT:{wid}:{cid}")
            deleted += 1
            print(json.dumps({
                "stage": "ONE_COMMENT_REMOVED", "workout_id": wid, "comment_id": cid,
                "transport_success": not response.is_error,
                "readback_verified": True,
            }), flush=True)

        # Final independent entire-batch check.
        for entry in m["entries"]:
            current = await get_workout(client, athlete_id, entry["workout_id"])
            must(choose_comment(current, entry) is None,
                 f"FINAL_COMMENT_REAPPEARED:{entry['comment_id']}")
        print(json.dumps({
            "stage": "WORKOUT_COMMENT_CLEANUP_VERIFIED",
            "athlete_id": athlete_id, "requested": len(checks),
            "deleted": deleted, "already_absent": len(checks) - deleted,
            "all_workouts_preserved": True,
        }), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run()))
    except (SafeStop, KeyError, ValueError, OSError, TypeError) as exc:
        print(json.dumps({"stage": "SAFE_STOP", "reason": str(exc)}), flush=True)
        raise SystemExit(2)
