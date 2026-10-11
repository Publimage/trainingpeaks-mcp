"""Read-only authorized GET of Peaksware-native Strength workout libraries."""
from __future__ import annotations
import asyncio,json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE

OWNER=2116886
LIBS={3890637:"[MCP TEST] Integration Lab",3891875:"IRONMAN MASTER | Forza",3894341:"CHASING THE SLOT | Forza — DRAFT NATIVE"}

def endpoint(lib_id:int)->str:
    assert lib_id in LIBS
    return f"/rx/activity/v1/libraryContent/workoutLibrary/{lib_id}"

def shape(obj):
    if isinstance(obj,list):
        return {"shape":"list","count":len(obj),"samples":[{"id":z.get("id"),"type":z.get("workoutLibraryItemType"),
                       "title":str(z.get("title") or "")[:100],"keys":sorted(z.keys())[:22],
                       "workout_type":z.get("workout",{}).get("workoutType") if isinstance(z.get("workout"),dict) else type(z.get("workout")).__name__,
                       "workout_keys":sorted(z.get("workout",{}).keys())[:22] if isinstance(z.get("workout"),dict) else [],
                       "blocks":len(z.get("workout",{}).get("blocks") or []) if isinstance(z.get("workout"),dict) else None,
                       "native_id":z.get("workout",{}).get("id") if isinstance(z.get("workout"),dict) else None,
                       "native_calendar_id":z.get("workout",{}).get("calendarId") if isinstance(z.get("workout"),dict) else None,
                       "native_prescribed_date":z.get("workout",{}).get("prescribedDate") if isinstance(z.get("workout"),dict) else None,
                       "block_summary":[{"type":b.get("blockType"),"title":b.get("title"),"prescriptions":len(b.get("prescriptions") or [])} for b in (z.get("workout",{}).get("blocks") or [])[:10]] if isinstance(z.get("workout"),dict) else []}
                       for z in obj[:12] if isinstance(z,dict)]}
    if isinstance(obj,dict):
        return {"shape":"dict","keys":sorted(obj.keys())[:30],
                "data":shape(obj["data"]) if isinstance(obj.get("data"),(list,dict)) else None}
    return {"shape":type(obj).__name__}

async def main()->int:
    async with TPClient() as client:
        me=await client._get_user_data()
        if not isinstance(me,dict) or me.get("personId")!=OWNER:
            print(json.dumps({"stage":"STOP_OWNER","writes":0}));return 2
        libs=await client.get("/exerciselibrary/v2/libraries")
        by_id={z.get("exerciseLibraryId"):z for z in libs.data} if not libs.is_error and isinstance(libs.data,list) else {}
        if any(not by_id.get(i) or by_id[i].get("libraryName")!=n or by_id[i].get("ownerId")!=OWNER for i,n in LIBS.items()):
            print(json.dumps({"stage":"STOP_LIBRARIES","writes":0}));return 3
        _,token,error=await _access(client)
        if error or not token:
            print(json.dumps({"stage":"STOP_AUTH","writes":0}));return 4
        summary={}
        async with httpx.AsyncClient(timeout=20,follow_redirects=False) as http:
            for lib in LIBS:
                path=endpoint(lib)
                try:
                    response=await http.get(STRENGTH_API_BASE+path,headers=_headers(token))
                    data=response.json() if response.status_code==200 else {}
                    items=data.get("data") if isinstance(data,dict) else data
                    compact=[{"id":x.get("id"),"title":x.get("title"),
                              "time":{k:w.get(k) for k in ("totalTimePlanned","durationPlanned","plannedDurationInSeconds","durationInSeconds","timePlanned") if w.get(k) is not None}}
                             for x in (items if isinstance(items,list) else []) if isinstance(x,dict)
                             for w in [x.get("workout") or {}] if isinstance(w,dict)]
                    print(json.dumps({"stage":"NATIVE_LIBRARY_GET","library":lib,"http":response.status_code,
                                      "items":compact,"writes":0},ensure_ascii=False),flush=True)
                    if response.status_code==200 and isinstance(items,list):
                        summary[str(lib)]={"total":len(items),"native_structured_strength":sum(1 for x in items if isinstance(x,dict) and x.get("workoutLibraryItemType")=="ActivityWorkoutTemplate" and isinstance(x.get("workout"),dict) and x["workout"].get("workoutType")=="StructuredStrength"),"ids_unique":len({str(x.get("id")) for x in items if isinstance(x,dict)})==len(items),"titles_unique":len({str(x.get("title")) for x in items if isinstance(x,dict)})==len(items),"undated":all(isinstance(x.get("workout"),dict) and x["workout"].get("calendarId") is None and x["workout"].get("prescribedDate") is None for x in items if isinstance(x,dict))}
                    else:
                        summary[str(lib)]={"http":response.status_code}
                except (httpx.RequestError,ValueError,TypeError):
                    print(json.dumps({"stage":"NETWORK_OR_PARSE_STOP","library":lib,"writes":0}),flush=True)
    print(json.dumps({"stage":"COMPACT_NATIVE_LIBRARY_SUMMARY","libraries":summary,"writes":0},ensure_ascii=False),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
