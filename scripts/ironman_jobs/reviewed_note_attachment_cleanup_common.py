"""Reviewed, manifest-driven cleanup of obsolete native Calendar Note PDFs.

The preview path never writes. The guarded publish path deletes only exact
obsolete attachment IDs after readback confirms all three replacement/retained
PDFs already exist. No upload, note PUT, workout edit or athlete writes.
"""
import asyncio
import json
from pathlib import Path

from tp_mcp.client import TPClient

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data" / "ironman_reviewed_note_attachment_cleanup.json"


class SafeStop(Exception):
    pass


def require(ok, msg):
    if not ok:
        raise SafeStop(msg)


def uid(note):
    return int(note.get("id") or note.get("calendarNoteId") or note.get("noteId") or 0)


def inventory(note):
    result = {}
    for value in note.get("attachments") or []:
        key = int(value["id"])
        require(key not in result, "DUPLICATE_ATTACHMENT_ID")
        result[key] = (str(value["fileName"]), int(value["contentLength"]))
    return result


def load_manifest():
    cfg = json.loads(MANIFEST.read_text(encoding="utf-8"))
    require(cfg.get("schema") == "IRONMAN_NOTE_ATTACHMENT_CLEANUP_V1" and
            cfg.get("configured") is True, "MANIFEST_DISABLED")
    required = ("owner_person_id", "plan_id", "plan_person_id", "plan_title",
                "plan_week_count", "plan_workout_count", "plan_notes_count",
                "plan_public", "plan_price", "notes_date_from", "notes_date_to",
                "note_id", "note_title", "attachments")
    require(all(k in cfg for k in required), "MANIFEST_MISSING_FIELD")
    rows = cfg["attachments"]
    require(isinstance(rows, list) and len(rows) >= 3, "MANIFEST_PDF_COUNT")
    ids = [int(v["id"]) for v in rows]
    require(len(ids) == len(set(ids)), "DUPLICATE_MANIFEST_ID")
    require(all(v["action"] in ("keep", "remove") and
                str(v["name"]).lower().endswith(".pdf") and int(v["bytes"]) > 100
                for v in rows), "MANIFEST_PDF_SHAPE")
    keep = {int(v["id"]): (v["name"], int(v["bytes"]))
            for v in rows if v["action"] == "keep"}
    remove = {int(v["id"]): (v["name"], int(v["bytes"]))
              for v in rows if v["action"] == "remove"}
    require(len(keep) >= 1 and len(remove) >= 1, "MANIFEST_EMPTY_TARGET")
    require(all(isinstance(cfg[k], int) and cfg[k] > 0
                for k in ("owner_person_id", "plan_id", "plan_person_id",
                          "plan_week_count", "plan_workout_count",
                          "plan_notes_count", "plan_price", "note_id")),
            "MANIFEST_IDS_INVALID")
    return cfg, keep, remove


async def run(publish=False):
    cfg, keep, obsolete = load_manifest()
    plan_id, note_id = cfg["plan_id"], cfg["note_id"]
    async with TPClient() as c:
        me = await c._get_user_data()
        require(isinstance(me, dict) and me.get("personId") ==
                cfg["owner_person_id"], "WRONG_COACH")

        async def read_plan():
            r = await c.get(f"/plans/v1/plans/{plan_id}")
            require(not r.is_error and isinstance(r.data, dict), "PLAN_READ_FAILED")
            p = r.data
            require((p.get("planId"), p.get("planPersonId"),
                     p.get("ownerPersonId"), p.get("title"),
                     p.get("weekCount"), p.get("workoutCount"),
                     p.get("isPublic"), p.get("price")) ==
                    (plan_id, cfg["plan_person_id"], cfg["owner_person_id"],
                     cfg["plan_title"], cfg["plan_week_count"],
                     cfg["plan_workout_count"], cfg["plan_public"],
                     cfg["plan_price"]), "PLAN_SCOPE_DRIFT")
            return p

        async def read_notes():
            r = await c.get(f"/plans/v1/plans/{plan_id}/calendarNote/"
                            f"{cfg['notes_date_from']}/{cfg['notes_date_to']}")
            require(not r.is_error and isinstance(r.data, list),
                    "NOTES_READ_FAILED")
            require(len(r.data) == cfg["plan_notes_count"],
                    "NATIVE_NOTE_COUNT_DRIFT")
            notes = {uid(n): n for n in r.data}
            require(len(notes) == len(r.data) and note_id in notes,
                    "NATIVE_NOTE_ID_DRIFT")
            return notes

        await read_plan()
        baseline = await read_notes()
        readme = baseline[note_id]
        require(readme.get("title") == cfg["note_title"], "NOTE_TITLE_DRIFT")
        require(len(readme.get("description") or "") > 200,
                "NOTE_DESCRIPTION_DRIFT")
        all_expected = dict(keep, **{})  # explicit copy
        all_expected.update(obsolete)
        current = inventory(readme)
        require(all(current.get(i) == pair for i, pair in keep.items()),
                "CURRENT_PDF_MISSING_OR_CHANGED")
        require(all(i in all_expected and all_expected[i] == pair
                    for i, pair in current.items()), "UNREVIEWED_ATTACHMENT_DRIFT")
        outstanding = [i for i in obsolete if i in current]
        other_notes = {i: n for i, n in baseline.items() if i != note_id}
        unchanged_fields = {k: v for k, v in readme.items() if k != "attachments"}

        print(json.dumps({"stage": "NOTE_PDF_CLEANUP_PREFLIGHT_PASS",
                          "plan": plan_id, "note": note_id,
                          "retain": sorted(keep), "obsolete": sorted(obsolete),
                          "pending_delete": outstanding,
                          "already_removed": sorted(set(obsolete) - set(outstanding)),
                          "preview_only": not publish, "provider_writes": 0}),
              flush=True)
        if not publish:
            return 0

        for old_id in outstanding:
            # A destructive request has no retry. Reconcile any ambiguity by GET.
            request_error = None
            try:
                r = await c._request(
                    "DELETE",
                    f"/plans/v1/plans/{plan_id}/calendarNote/{note_id}/attachments/{old_id}",
                    _retry_on_401=False)
                if r.is_error:
                    request_error = "PROVIDER_DELETE_ERROR"
            except Exception as exc:
                request_error = "DELETE_RESPONSE_UNCERTAIN_" + type(exc).__name__

            now = await read_notes()
            require(all(now[i] == n for i, n in other_notes.items()),
                    "OTHER_NOTE_CHANGED")
            fresh = now[note_id]
            require({k: v for k, v in fresh.items() if k != "attachments"} ==
                    unchanged_fields, "README_CONTENT_CHANGED")
            fresh_att = inventory(fresh)
            require(all(fresh_att.get(i) == val for i, val in keep.items()),
                    "PRESERVED_ATTACHMENT_CHANGED")
            require(all(i in all_expected and all_expected[i] == val
                        for i, val in fresh_att.items()), "UNEXPECTED_ATTACHMENT")
            require(old_id not in fresh_att,
                    request_error or "DELETE_UNVERIFIED_NO_BLIND_RETRY")
            print(json.dumps({"stage": "ONE_OLD_PDF_DELETED_VERIFIED",
                              "attachment_id": old_id}), flush=True)

        final = await read_notes()
        require(inventory(final[note_id]) == keep, "FINAL_THREE_PDFS_MISMATCH")
        require(all(final[i] == n for i, n in other_notes.items()),
                "FINAL_OTHER_NOTES_CHANGED")
        require({k: v for k, v in final[note_id].items()
                 if k != "attachments"} == unchanged_fields,
                "FINAL_README_CHANGED")
        await read_plan()
        print(json.dumps({"stage": "NOTE_PDF_CLEANUP_PUBLISH_VERIFIED",
                          "plan": plan_id, "note": note_id,
                          "preserved": sorted(keep),
                          "deleted": sorted(obsolete),
                          "pdf_count": len(keep),
                          "notes": len(final),
                          "workouts": cfg["plan_workout_count"],
                          "public": cfg["plan_public"],
                          "price": cfg["plan_price"],
                          "library_writes": 0,
                          "athlete_calendar_writes": 0},
                         ensure_ascii=False), flush=True)
        return 0


def main(publish):
    try:
        raise SystemExit(asyncio.run(run(publish)))
    except SafeStop as exc:
        print(json.dumps({"stage": "SAFE_STOP", "reason": str(exc),
                          "no_blind_retry": True}), flush=True)
        raise SystemExit(2)
