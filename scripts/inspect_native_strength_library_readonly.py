"""Read-only inspection of native TrainingPeaks Strength Builder libraries.

The classic Workout Library reader may not expose native Strength Builder items.
This probe makes GET requests only, never POST/PUT/DELETE, and never prints tokens.
Do not infer absence of native Strength templates from an empty classic API list.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _headers, STRENGTH_API_BASE

OWNER_ID = 2116886
TARGET_LIB_ID = 3891875
LAB_LIB_ID = 3890637
TARGET_NAME = "IRONMAN MASTER | Forza"
LAB_NAME = "[MCP TEST] Integration Lab"
MANIFEST = Path(__file__).resolve().parents[1] / "data" / "intermediate_strength_native_library_queue.json"

# GET only. These are investigation candidates, not verified provider contracts.
CANDIDATES = [
    ("tpapi", f"/exerciselibrary/v2/libraries/{TARGET_LIB_ID}/items?includeNewStrength=true"),
    ("tpapi", f"/exerciselibrary/v3/libraries/{TARGET_LIB_ID}/items"),
    ("tpapi", f"/exerciselibrary/v2/libraries/{TARGET_LIB_ID}/strengthworkouts"),
    ("tpapi", f"/exerciselibrary/v2/libraries/{TARGET_LIB_ID}/items/strength"),
    ("strength", f"/rx/activity/v1/workouts/library/{TARGET_LIB_ID}"),
    ("strength", f"/rx/activity/v1/workouts/libraries/{TARGET_LIB_ID}"),
    ("strength", f"/rx/activity/v1/libraries/{TARGET_LIB_ID}/workouts"),
    ("strength", f"/rx/activity/v1/library/{TARGET_LIB_ID}/workouts"),
    ("strength", f"/rx/activity/v1/workouts/templates/{TARGET_LIB_ID}"),
    ("strength", "/rx/activity/v1/workouts/library"),
    ("strength", "/rx/activity/v1/workouts/libraries"),
    ("strength", "/rx/activity/v1/workouts/templates"),
    ("strength", f"/rx/workoutlibrary/v1/libraries/{TARGET_LIB_ID}"),
]

def _extract(obj: Any) -> tuple[list[dict], str]:
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)], "list"
    if isinstance(obj, dict):
        for key in ("data", "items", "results", "workouts", "templates", "libraries", "content"):
            val = obj.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)], f"{key}[list]"
            if isinstance(val, dict):
                for inner in ("items", "workouts", "templates", "results"):
                    if isinstance(val.get(inner), list):
                        return [x for x in val[inner] if isinstance(x, dict)], f"{key}.{inner}[list]"
        return [], "dict:" + ",".join(sorted(str(k) for k in obj.keys())[:8])
    return [], type(obj).__name__

def _names(xs: list[dict]) -> list[dict]:
    return [
        {"id": str(x.get("exerciseLibraryItemId") or x.get("id") or "")[:32],
         "title": str(x.get("itemName") or x.get("title") or x.get("name") or "")[:100],
         "kind": str(x.get("exerciseLibraryItemType") or x.get("workoutType") or x.get("type") or "")[:45]}
        for x in xs[:35]
    ]

async def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    variants = manifest.get("variants")
    if (manifest.get("provider_library_id") != TARGET_LIB_ID
        or manifest.get("unique_native_variants") != 19
        or not isinstance(variants, list) or len(variants) != 19):
        print("STOP: manifest canonico incompleto; nessuna scrittura.")
        return 2
    print("MANIFEST: 19/19 varianti preparate; modalità SOLA LETTURA.", flush=True)

    async with TPClient() as tp:
        me = await tp._get_user_data()
        if not isinstance(me, dict) or me.get("personId") != OWNER_ID:
            print("STOP: identità coach non confermata; nessuna scrittura.")
            return 2
        owners = await tp.get("/exerciselibrary/v2/libraries")
        if owners.is_error or not isinstance(owners.data, list):
            print("STOP: elenco librerie non accessibile.")
            return 2
        by_id = {lib.get("exerciseLibraryId"): lib for lib in owners.data}
        for i, name in ((TARGET_LIB_ID, TARGET_NAME), (LAB_LIB_ID, LAB_NAME)):
            x = by_id.get(i)
            if not x or x.get("libraryName") != name or x.get("ownerId") != OWNER_ID:
                print("STOP: proprietà libreria discordante:", i)
                return 2
        normal = await tp.get(f"/exerciselibrary/v2/libraries/{TARGET_LIB_ID}/items")
        if normal.is_error or not isinstance(normal.data, list):
            print("STOP: reader library classic non disponibile.")
            return 2
        classic = normal.data
        print(f"LIBRERIA CLASSICA: {len(classic)} oggetti (sono distinti dai modelli nativi).")
        print("CLASSIC_TYPES:", sorted({str(z.get("exerciseLibraryItemType")) for z in classic}))
        print("NOTA: questo conteggio NON prova che i modelli Builder siano assenti.", flush=True)

        token = await tp._ensure_access_token()
        if not token.success or not tp._token_cache.access_token:
            print("STOP: token Strength non disponibile.")
            return 2
        h = _headers(tp._token_cache.access_token)
        async with httpx.AsyncClient(timeout=16, follow_redirects=False) as http:
            source = await http.get(
                f"{STRENGTH_API_BASE}/rx/activity/v1/workouts/33973000", headers=h
            )
            src = {}
            if source.status_code == 200:
                try:
                    src = source.json().get("data") or {}
                except (ValueError, AttributeError):
                    src = {}
            if source.status_code != 200 or src.get("workoutType") != "StructuredStrength":
                print("STOP: Strength source access failed", source.status_code)
                return 2
            print("STRENGTH API: autenticazione verificata; workout sorgente nativo leggibile.", flush=True)

            sem = asyncio.Semaphore(4)

            async def scan(host: str, path: str) -> dict:
                base = "https://tpapi.trainingpeaks.com" if host == "tpapi" else STRENGTH_API_BASE
                async with sem:
                    try:
                        rr = await http.get(base + path, headers=h)
                        if rr.status_code != 200:
                            return {"host": host, "path": path, "http": rr.status_code}
                        try:
                            parsed = rr.json()
                        except ValueError:
                            return {"host": host, "path": path, "http": 200, "payload": "not JSON"}
                        items, shape = _extract(parsed)
                        return {"host": host, "path": path, "http": 200, "shape": shape,
                                "count": len(items), "items": _names(items)}
                    except (httpx.HTTPError, ValueError):
                        return {"host": host, "path": path, "http": "NETWORK_ERROR"}

            scan_results = await asyncio.gather(*(scan(a, b) for a, b in CANDIDATES))
        for r in scan_results:
            items = r.pop("items", None)
            print("GET_PROBE:", json.dumps(r, ensure_ascii=False), flush=True)
            if items:
                print("SAMPLE_ITEMS:", json.dumps(items[:25], ensure_ascii=False), flush=True)

        matches = [r for r in scan_results if r.get("http") == 200 and r.get("count", 0) >= 19]
        print("NATIVE_LIB_VISIBILITY:", "POSSIBLE_ROUTE_FOUND" if matches else "NOT_YET_PROVEN")
        print("SCRITTURE_PROVIDER: 0")
        return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
