"""Read-only inspect all seven native CHASING Strength Builder Coach Notes.
No writes, no athlete calendar. Output bounded exercise IDs and rest notes.
"""
import asyncio,json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
OWNER=2116886
LIB=3894341
IDS={"330618","330621","330624","330626","330628","330629","330631"}
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  if not isinstance(me,dict) or me.get("personId")!=OWNER: raise RuntimeError("WRONG_OWNER")
  _,token,error=await _access(c)
  if error or not token: raise RuntimeError("NO_NATIVE_ACCESS")
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   rr=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/libraryContent/workoutLibrary/{LIB}",headers=_headers(token))
   if rr.status_code!=200:raise RuntimeError("LIBRARY_GET_FAILED")
   data=rr.json()
   items=data if isinstance(data,list) else data.get("data") or []
   if len(items)!=7 or {str(x.get("id")) for x in items}!=IDS:raise RuntimeError("LIBRARY_SCOPE_DRIFT")
   for item in sorted(items,key=lambda x:x["title"]):
    w=item.get("workout") or {}
    blocks=[]
    for n,b in enumerate(w.get("blocks") or []):
     exercises=[]
     for p in b.get("prescriptions") or []:
      x=p.get("exercise") or {}
      exercises.append({"id":str(x.get("id")),"title":x.get("title"),"sets":len(p.get("sets") or []),
       "coachNotes":p.get("coachNotes"),"set_samples":[{v.get("parameter"):v.get("prescribedValue") for v in (set_.get("parameterValues") or [])} for set_ in (p.get("sets") or [])[:2]]})
     blocks.append({"index":n,"type":b.get("blockType"),"name":b.get("title"),"coachNotes":b.get("coachNotes"),"exercises":exercises})
    print(json.dumps({"id":item.get("id"),"title":item.get("title"),"workout_duration":w.get("prescribedDurationInSeconds"),
     "instructions":w.get("instructions"),"blocks":blocks},ensure_ascii=False),flush=True)
 return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
