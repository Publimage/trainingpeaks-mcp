"""Guarded generic native PDF attachment from a coach-owned plan note to one athlete note.

Only an existing note is modified. No notes/workouts/strength are created or deleted.
Target is revision-controlled in data/ironman_athlete_note_pdf_manifest.json.
Reuse a provider-proven athlete calendar-note attachment route.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path

from tp_mcp.client import TPClient

CFG_PATH = Path(__file__).resolve().parents[2] / "data/ironman_athlete_note_pdf_manifest.json"


def emit(stage: str, **fields: object) -> None:
    print(json.dumps({"stage": stage, **fields}, ensure_ascii=False), flush=True)


def require(ok: bool, code: str) -> None:
    if not ok:
        raise RuntimeError(code)


def note_id(n: dict) -> int:
    return int(n.get("id") or n.get("calendarNoteId") or 0)


def matching_attachment(n: dict, cfg: dict) -> list[dict]:
    return [
        x for x in n.get("attachments") or []
        if x.get("fileName") == cfg["file_name"]
        and int(x.get("contentLength") or -1) == cfg["size"]
        and x.get("id") is not None
    ]


def verify_config(cfg: dict) -> None:
    require(cfg.get("schema") == "IRONMAN_ATHLETE_NOTE_PDF_V1", "MANIFEST_SCHEMA")
    require(cfg.get("owner_id") == 2116886, "OWNER_SCOPE")
    for key in ("athlete_id", "target_note_id", "source_plan_id",
                "source_plan_note_id", "source_attachment_id", "size",
                "expected_athlete_note_count"):
        require(type(cfg.get(key)) is int and cfg[key] > 0, "MANIFEST_" + key)
    require(cfg["target_date"] >= cfg["athlete_calendar_start"]
            and cfg["target_date"] <= cfg["athlete_calendar_end"], "DATE_SCOPE")
    require(cfg["file_name"].endswith(".pdf") and "/" not in cfg["file_name"],
            "PDF_FILENAME")
    require(len(cfg["sha256"]) == 64, "PDF_DIGEST")


async def main() -> int:
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    verify_config(cfg)
    owner, athlete, note = cfg["owner_id"], cfg["athlete_id"], cfg["target_note_id"]
    plan, plan_note = cfg["source_plan_id"], cfg["source_plan_note_id"]
    note_path = f"/fitness/v1/athletes/{athlete}/calendarNote/{note}"
    note_range = (f"/fitness/v2/athletes/{athlete}/calendarNote/"
                  f"{cfg['athlete_calendar_start']}/{cfg['athlete_calendar_end']}")
    source_notes_path = (f"/plans/v1/plans/{plan}/calendarNote/"
                         f"{cfg['source_plan_note_date']}/{cfg['source_plan_note_date']}")

    async with TPClient() as c:
        me = await c._get_user_data()
        require(isinstance(me, dict) and me.get("personId") == owner,
                "COACH_OWNER_MISMATCH")
        plan_result = await c.get(f"/plans/v1/plans/{plan}")
        require(not plan_result.is_error and isinstance(plan_result.data, dict)
                and plan_result.data.get("planId") == plan
                and plan_result.data.get("weekCount") == 8
                and plan_result.data.get("workoutCount") == 74, "SOURCE_PLAN_DRIFT")

        source_notes = await c.get(source_notes_path)
        require(not source_notes.is_error and isinstance(source_notes.data, list),
                "SOURCE_NOTES_UNREADABLE")
        sources = [n for n in source_notes.data if note_id(n) == plan_note]
        require(len(sources) == 1 and
                sources[0].get("title") == cfg["target_note_title"] and
                len(matching_attachment(sources[0], cfg)) == 1,
                "SOURCE_NOTE_PDF_DRIFT")
        source = sources[0]
        a = await c.get(note_path)
        require(not a.is_error and isinstance(a.data, dict), "TARGET_NOTE_UNREADABLE")
        target = a.data
        require(note_id(target) == note and
                target.get("title") == cfg["target_note_title"] and
                str(target.get("noteDate") or target.get("date") or "").startswith(cfg["target_date"]) and
                target.get("description") == source.get("description"),
                "TARGET_NOTE_ID_DATE_OR_BODY_DRIFT")
        original_attachments = target.get("attachments") or []
        require(isinstance(original_attachments, list), "TARGET_ATTACHMENT_INVALID")

        inv = await c.get(note_range)
        require(not inv.is_error and isinstance(inv.data, list), "ATHLETE_NOTES_UNREADABLE")
        before = inv.data
        require(len(before) == cfg["expected_athlete_note_count"]
                and len(set(note_id(n) for n in before)) == len(before)
                and len([n for n in before if note_id(n) == note]) == 1,
                "ATHLETE_NOTE_INVENTORY_DRIFT")

        existing = matching_attachment(target, cfg)
        require(len(existing) <= 1, "DUPLICATE_EXISTING_PDF")
        if existing:
            require(len(original_attachments) == 1, "UNEXPECTED_OTHER_ATTACHMENTS")
            emit("ALREADY_PRESENT", athlete_id=athlete, note_id=note,
                 attachment_id=existing[0]["id"], provider_writes=0)
            return 0
        require(not original_attachments, "TARGET_HAS_OTHER_ATTACHMENTS")

        await c._ensure_client()
        auth = await c._ensure_access_token()
        require(auth.success, "TP_AUTH_UNAVAILABLE")
        source_file = await c._client.get(
            c.base_url + f"/plans/v1/plans/{plan}/calendarNote/{plan_note}/attachments/{cfg['source_attachment_id']}",
            headers=c._get_headers(), timeout=40)
        require(source_file.status_code == 200, "SOURCE_BINARY_UNAVAILABLE")
        source_b64 = source_file.json().get("data")
        require(isinstance(source_b64, str), "SOURCE_BINARY_MISSING")
        blob = base64.b64decode(source_b64, validate=True)
        require(len(blob) == cfg["size"] and blob.startswith(b"%PDF-") and
                hashlib.sha256(blob).hexdigest() == cfg["sha256"],
                "SOURCE_BINARY_HASH_MISMATCH")
        emit("PDF_SOURCE_VERIFIED", bytes=len(blob), sha256=cfg["sha256"])

        payload = {
            "athleteId": athlete, "noteId": note, "fileName": cfg["file_name"],
            "contentType": "application/pdf", "data": source_b64,
        }
        try:
            result = await c._client.request(
                "POST", c.base_url + note_path + "/attachments",
                headers=c._get_headers(), json=payload, timeout=60)
            result_status = result.status_code
        except Exception:
            result_status = None

        # Readback always, including ambiguous transport outcomes; never retry POST.
        after_note_result = await c.get(note_path)
        require(not after_note_result.is_error and isinstance(after_note_result.data, dict),
                "POST_OUTCOME_UNCERTAIN_NOTE_READ_FAILED")
        final = after_note_result.data
        files = matching_attachment(final, cfg)
        require(len(files) == 1 and len(final.get("attachments") or []) == 1,
                "POST_NOT_VERIFIED_STATUS_" + str(result_status))
        require(note_id(final) == note and
                final.get("title") == target.get("title") and
                final.get("description") == target.get("description") and
                str(final.get("noteDate") or final.get("date") or "")[:10] == cfg["target_date"],
                "FINAL_NOTE_CHANGED")

        after_inv_result = await c.get(note_range)
        require(not after_inv_result.is_error and isinstance(after_inv_result.data, list),
                "POST_OUTCOME_UNCERTAIN_INVENTORY_READ_FAILED")
        after = after_inv_result.data
        require(len(after) == len(before) and
                {note_id(n) for n in after} == {note_id(n) for n in before},
                "AFTER_NOTE_INVENTORY_CHANGED")
        unchanged = {note_id(n): n for n in before if note_id(n) != note}
        for n in after:
            if note_id(n) != note:
                require(n == unchanged[note_id(n)], "NON_TARGET_NOTE_CHANGED")
        emit("ATHLETE_NATIVE_PDF_VERIFIED", athlete_id=athlete,
             note_id=note, attachment_id=files[0]["id"],
             file_name=cfg["file_name"], bytes=cfg["size"],
             sha256=cfg["sha256"], note_count=len(after), provider_writes=1)
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        emit("SAFE_STOP", error=str(exc)[:250])
        raise SystemExit(2)
