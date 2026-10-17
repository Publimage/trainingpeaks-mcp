"""Guarded E2E: create native TrainingPeaks archive folder and assign exactly six MCP TEST plans.

Authorized scope:
- owner 2116886 only
- exact target folder: ARCHIVIATI | TEST MCP
- exact six private/unpriced MCP TEST plan IDs/titles
- canary first: plan 684484 only, provider readback, then remaining five
- all 21 plan metadata must remain unchanged
- no athlete calendar/library writes
- no blind retry after ambiguous POST
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from tp_mcp.client import TPClient

OWNER = 2116886
FOLDER_NAME = "ARCHIVIATI | TEST MCP"
CANARY_ID = 684484
TARGETS = {
    684762: "[MCP TEST] FIELD EDIT PATCH LAB 2026-10-10",
    684463: "[MCP TEST] IRONMAN Intermediate 24W - Archive Pilot",
    684555: "[MCP TEST] Swim Master E2E QA 2026-10-09",
    684543: "[MCP TEST] TP Native Strength Plan Route 2026-10-09",
    684484: "[MCP TEST] TP Plan DELETE Route Probe 2026-10-09",
    684206: "[MCP TEST] Training Plan — Swim Bike Run",
}
PROTECTED = {
    679801: ("ALBERTO FAZI ENDURANCE | First Ironman | 24 settimane | Beginner | Smart Start incluso | Italiano", True, 179.0),
    684602: ("ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano", False, None),
    685173: ("ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA", False, None),
}
PLAN_KEYS = ("title", "weekCount", "workoutCount", "planCategory", "subcategory", "isPublic", "price")

class Stop(Exception):
    pass

def log(**kw):
    print(json.dumps(kw, ensure_ascii=False, sort_keys=True), flush=True)

def must(value, message):
    if not value:
        raise Stop(message)

def plan_snapshot(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {
        int(p["planId"]): {k: p.get(k) for k in PLAN_KEYS}
        for p in rows
        if isinstance(p, dict) and p.get("planId") is not None
    }

def folder_title(row: dict[str, Any]) -> str:
    return str(row.get("title") or row.get("folderName") or row.get("name") or "")

def folder_id(row: dict[str, Any]) -> str | None:
    value = row.get("folderId", row.get("id"))
    if value is None:
        return None
    text = str(value).strip()
    return text or None

def folder_plan_ids(row: dict[str, Any]) -> set[int]:
    raw = row.get("planIds") or []
    out = set()
    for value in raw:
        try:
            out.add(int(value))
        except (TypeError, ValueError):
            pass
    return out

async def main() -> int:
    async with TPClient() as c:
        me = await c._get_user_data()
        must(isinstance(me, dict) and me.get("personId") == OWNER, "WRONG_OWNER")

        async def read_plans():
            r = await c.get("/plans/v1/plans")
            must(not r.is_error and isinstance(r.data, list), "PLAN_INVENTORY_READ_FAILED")
            return r.data

        async def read_folders():
            r = await c.get("/planfolder/v1/folder/all")
            must(not r.is_error and isinstance(r.data, list), "FOLDER_INVENTORY_READ_FAILED")
            return r.data

        async def resolve_target_folder(folders):
            matches = [x for x in folders if isinstance(x, dict) and folder_title(x) == FOLDER_NAME]
            must(len(matches) <= 1, "DUPLICATE_TARGET_FOLDER")
            return matches[0] if matches else None

        plans_before = await read_plans()
        must(len(plans_before) == 21, f"PLAN_COUNT_DRIFT:{len(plans_before)}")
        by_id = {int(x["planId"]): x for x in plans_before if isinstance(x, dict) and x.get("planId") is not None}
        must(set(TARGETS).issubset(by_id), "TARGET_PLAN_MISSING")

        for pid, title in TARGETS.items():
            p = by_id[pid]
            must(p.get("title") == title, f"TARGET_TITLE_DRIFT:{pid}")
            must(p.get("isPublic") is False, f"TARGET_PUBLIC_FORBIDDEN:{pid}")
            must(p.get("price") in (None, 0, 0.0), f"TARGET_PRICED_FORBIDDEN:{pid}")
            must(title.startswith("[MCP TEST]"), f"TARGET_NOT_MCP_TEST:{pid}")

        for pid, (title, is_public, price) in PROTECTED.items():
            p = by_id.get(pid)
            must(p is not None, f"PROTECTED_PLAN_MISSING:{pid}")
            must(p.get("title") == title, f"PROTECTED_TITLE_DRIFT:{pid}")
            must(p.get("isPublic") is is_public, f"PROTECTED_PUBLIC_DRIFT:{pid}")
            must(p.get("price") == price, f"PROTECTED_PRICE_DRIFT:{pid}")

        snapshot = plan_snapshot(plans_before)
        folders_before = await read_folders()
        target = await resolve_target_folder(folders_before)

        if target is not None:
            current_ids = folder_plan_ids(target)
            must(current_ids.issubset(set(TARGETS)), "TARGET_FOLDER_CONTAINS_NON_TARGET_PLAN")
            fid = folder_id(target)
            must(fid is not None, "TARGET_FOLDER_ID_MISSING")
            log(stage="PREFLIGHT_EXISTING_FOLDER", folder_id=fid,
                current_plan_ids=sorted(current_ids), provider_writes=0)
        else:
            log(stage="PREFLIGHT_CREATE_FOLDER", plan_count=len(plans_before),
                target_ids=sorted(TARGETS), provider_writes=0)
            try:
                response = await c._request(
                    "POST", "/planfolder/v1/folder",
                    json={"folderName": FOLDER_NAME}, _retry_on_401=False,
                )
            except Exception as exc:
                # Ambiguous POST: read state; never replay blindly.
                after = await read_folders()
                target = await resolve_target_folder(after)
                if target is None:
                    log(stage="CREATE_FOLDER_AMBIGUOUS_STOP",
                        error=type(exc).__name__, retry=False, provider_writes="UNKNOWN")
                    return 4
            else:
                if response.is_error:
                    after = await read_folders()
                    target = await resolve_target_folder(after)
                    if target is None:
                        log(stage="CREATE_FOLDER_REJECTED_STOP",
                            status=getattr(response, "status_code", None),
                            message=str(response.message)[:160],
                            retry=False, provider_writes=0)
                        return 4
                else:
                    after = await read_folders()
                    target = await resolve_target_folder(after)
            must(target is not None, "CREATE_FOLDER_NO_READBACK")
            fid = folder_id(target)
            must(fid is not None, "CREATED_FOLDER_ID_MISSING")
            must(folder_plan_ids(target) == set(), "NEW_FOLDER_NOT_EMPTY")
            log(stage="CREATE_FOLDER_VERIFIED", folder_id=fid, provider_writes=1)

        # Re-read source of truth before membership writes.
        folders = await read_folders()
        target = await resolve_target_folder(folders)
        must(target is not None and folder_id(target) == fid, "TARGET_FOLDER_READBACK_DRIFT")
        current = folder_plan_ids(target)
        must(current.issubset(set(TARGETS)), "TARGET_FOLDER_CONTAINS_NON_TARGET_PLAN")

        async def assign_exact(plan_ids: list[int], stage: str) -> tuple[bool, set[int]]:
            if not plan_ids:
                return True, folder_plan_ids((await resolve_target_folder(await read_folders())) or {})
            try:
                resp = await c._request(
                    "POST", "/planfolder/v1/command/assignplanstofolder",
                    json={"folderId": fid, "planIds": plan_ids},
                    _retry_on_401=False,
                )
            except Exception as exc:
                rb = await resolve_target_folder(await read_folders())
                observed = folder_plan_ids(rb or {})
                log(stage=stage+"_AMBIGUOUS_READBACK", requested=plan_ids,
                    observed=sorted(observed), error=type(exc).__name__, retry=False)
                return set(plan_ids).issubset(observed), observed
            rb = await resolve_target_folder(await read_folders())
            observed = folder_plan_ids(rb or {})
            if resp.is_error and not set(plan_ids).issubset(observed):
                log(stage=stage+"_REJECTED", requested=plan_ids, observed=sorted(observed),
                    status=getattr(resp,"status_code",None), message=str(resp.message)[:160],
                    retry=False)
                return False, observed
            return set(plan_ids).issubset(observed), observed

        # Canary on the most disposable lab plan first.
        if CANARY_ID not in current:
            ok, observed = await assign_exact([CANARY_ID], "CANARY_ASSIGN")
            must(ok, "CANARY_ASSIGN_NOT_VERIFIED")
            must(observed.issubset(set(TARGETS)), "CANARY_FOLDER_CONTAMINATION")
            log(stage="CANARY_ASSIGN_VERIFIED", folder_id=fid,
                plan_id=CANARY_ID, folder_plan_ids=sorted(observed), provider_writes=1)
        else:
            log(stage="CANARY_ALREADY_VERIFIED", folder_id=fid, plan_id=CANARY_ID,
                provider_writes=0)

        rb = await resolve_target_folder(await read_folders())
        current = folder_plan_ids(rb or {})
        remaining = sorted(set(TARGETS) - current)
        if remaining:
            ok, observed = await assign_exact(remaining, "BATCH_ASSIGN")
            must(ok, "BATCH_ASSIGN_NOT_VERIFIED")
            must(observed == set(TARGETS), f"FINAL_FOLDER_MEMBERSHIP_MISMATCH:{sorted(observed)}")
            log(stage="BATCH_ASSIGN_VERIFIED", folder_id=fid,
                added=remaining, folder_plan_ids=sorted(observed), provider_writes=1)
        else:
            observed = current

        # Final invariants: exact membership and every plan metadata snapshot unchanged.
        folders_final = await read_folders()
        final_target = await resolve_target_folder(folders_final)
        must(final_target is not None and folder_id(final_target) == fid, "FINAL_FOLDER_MISSING")
        must(folder_plan_ids(final_target) == set(TARGETS), "FINAL_MEMBERSHIP_NOT_EXACT")

        plans_after = await read_plans()
        must(len(plans_after) == 21, f"FINAL_PLAN_COUNT_DRIFT:{len(plans_after)}")
        must(plan_snapshot(plans_after) == snapshot, "PLAN_METADATA_DRIFT")

        # Ensure no other folder contains any of the six targets.
        for folder in folders_final:
            if not isinstance(folder, dict) or folder_id(folder) == fid:
                continue
            overlap = folder_plan_ids(folder) & set(TARGETS)
            must(not overlap, f"TARGET_STILL_IN_OTHER_FOLDER:{folder_id(folder)}:{sorted(overlap)}")

        log(stage="COMPLETE_VERIFIED", folder_id=fid, folder_name=FOLDER_NAME,
            plan_ids=sorted(TARGETS), plan_count=21,
            all_other_plan_metadata_unchanged=True,
            athlete_calendar_writes=0, workout_library_writes=0)
        return 0

if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Stop as exc:
        log(stage="STOP_REVIEW", reason=str(exc), retry=False)
        raise SystemExit(2)
