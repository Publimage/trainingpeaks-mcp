"""One-shot LAB-ONLY probe: native StructuredStrength into Workout Library.

NO athlete calendars, NO dated workout writes, NO production library edits.
A library item is useful only after native-type and exercise-block readback.
The one POST is never retried on ambiguity.
"""
from __future__ import annotations

import asyncio
import json
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access, _headers, STRENGTH_API_BASE
import httpx

OWNER = 2116886
LIB_ID = 3890637
LIB_NAME = "[MCP TEST] Integration Lab"
NATIVE_SOURCE_ID = 33973000  # READ-ONLY verified StructuredStrength sample.
TITLE = "[MCP TEST] CHASING Strength Builder native library canary v1"
POST_PATH = f"/exerciselibrary/v1/libraries/{LIB_ID}/items"


def build_candidate(source: dict) -> dict:
    """Keep native Strength blocks together; never flatten to prose or intervals."""
    assert source.get("workoutType") == "StructuredStrength"
    blocks = source.get("blocks")
    assert isinstance(blocks, list) and blocks
    assert all(isinstance(b, dict) and b.get("prescriptions") for b in blocks)
    return {
        "exerciseLibraryId": LIB_ID,
        "exerciseLibraryItemType": "StructuredStrength",
        "itemName": TITLE,
        "workoutTypeId": 9,
        "description": "[MCP TEST] Native Strength library API canary — disposable.",
        "structure": {
            "workoutType": "StructuredStrength",
            "blocks": blocks,
            "instructions": source.get("instructions") or "",
        },
    }


def strict_readback(item: dict) -> bool:
    struct = item.get("structure") or {}
    blocks = struct.get("blocks") if isinstance(struct, dict) else None
    return (
        item.get("exerciseLibraryId") == LIB_ID
        and item.get("itemName") == TITLE
        and item.get("exerciseLibraryItemType") == "StructuredStrength"
        and item.get("workoutTypeId") == 9
        and isinstance(blocks, list) and len(blocks) >= 1
        and all(isinstance(b, dict) and b.get("prescriptions") for b in blocks)
    )


def report(**kwargs) -> None:
    print(json.dumps(kwargs, ensure_ascii=False, default=str), flush=True)


async def main() -> int:
    async with TPClient() as client:
        me = await client._get_user_data()
        if not isinstance(me, dict) or me.get("personId") != OWNER:
            report(stage="STOP",reason="coach owner not verified",writes=0)
            return 2
        response = await client.get("/exerciselibrary/v2/libraries")
        if response.is_error or not isinstance(response.data, list):
            report(stage="STOP",reason="library ownership unreadable",writes=0)
            return 2
        lib = next((z for z in response.data if z.get("exerciseLibraryId")==LIB_ID),None)
        if not lib or lib.get("libraryName") != LIB_NAME or lib.get("ownerId") != OWNER:
            report(stage="STOP",reason="lab library mismatch",writes=0)
            return 2
        target=f"/exerciselibrary/v2/libraries/{LIB_ID}/items"
        before=await client.get(target)
        if before.is_error or not isinstance(before.data,list):
            report(stage="STOP",reason="lab item read failed",writes=0)
            return 2
        matches=[z for z in before.data if z.get("itemName")==TITLE]
        if matches:
            report(stage="STOP_ALREADY_PRESENT",matches=len(matches),
                   readback_native=all(strict_readback(z) for z in matches),writes=0)
            return 0 if len(matches)==1 and strict_readback(matches[0]) else 3
        person_id,token,error=await _access(client)
        if error or not token:
            report(stage="STOP",reason="strength authentication failed",writes=0)
            return 2
        async with httpx.AsyncClient(timeout=16,follow_redirects=False) as http:
            src=await http.get(f"{STRENGTH_API_BASE}/rx/activity/v1/workouts/{NATIVE_SOURCE_ID}",headers=_headers(token))
            if src.status_code != 200:
                report(stage="STOP",reason="native source unavailable",http=src.status_code,writes=0)
                return 2
            source=src.json().get("data") or {}
        try:
            payload=build_candidate(source)
        except (AssertionError,TypeError,ValueError):
            report(stage="STOP",reason="native source invalid",writes=0)
            return 2
        report(stage="PREFLIGHT",lab_library=LIB_ID,pre_count=len(before.data),
               native_blocks=len(payload["structure"]["blocks"]),writes=0)
        # EXACTLY ONE LAB POST; do not retry if rejected, timed out, or ambiguous.
        try:
            created=await client._request("POST",POST_PATH,json=payload,_retry_on_401=False)
        except Exception as exc:
            report(stage="STOP_AMBIGUOUS_POST",kind=type(exc).__name__,retry=False)
            return 4
        if created.is_error:
            # Read once even after errors: some providers may have applied a write.
            after=await client.get(target)
            m=[z for z in (after.data if not after.is_error and isinstance(after.data,list) else []) if z.get("itemName")==TITLE]
            report(stage="API_REJECTED_OR_AMBIGUOUS",error_code=str(created.error_code),
                   matches_after=len(m),readback_native=len(m)==1 and strict_readback(m[0]),
                   retry=False)
            return 0 if len(m)==1 and strict_readback(m[0]) else 5
        after=await client.get(target)
        if after.is_error or not isinstance(after.data,list):
            report(stage="POST_ACCEPTED_READBACK_UNAVAILABLE",retry=False)
            return 6
        m=[z for z in after.data if z.get("itemName")==TITLE]
        native=len(m)==1 and strict_readback(m[0])
        report(stage="READBACK",lab_library=LIB_ID,after_count=len(after.data),
               matches=len(m),native=native,
               kind=m[0].get("exerciseLibraryItemType") if m else None,
               exercise_count=len((m[0].get("structure") or {}).get("blocks",[])) if m and isinstance(m[0].get("structure"),dict) else 0,
               item_id=m[0].get("exerciseLibraryItemId") if m else None,retry=False)
        return 0 if native and len(after.data)==len(before.data)+1 else 7


if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
