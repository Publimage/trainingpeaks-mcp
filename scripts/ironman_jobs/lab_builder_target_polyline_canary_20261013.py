"""Plan LAB only: canary for native Builder active target and polyline regeneration. Always restore."""
import asyncio,json,hashlib
from tp_mcp.client import TPClient
P=684206;WID=3994993213;OWNER=2116886;DATE1="2027-06-21";DATE2="2027-06-28"
def must(v,s):
 if not v:raise RuntimeError(s)
def dig(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
async def read(c):
 p=await c.get(f"/plans/v1/plans/{P}")
 must(not p.is_error and p.data.get("planId")==P and p.data.get("isPublic") is False and p.data.get("workoutCount")==6,"LAB_SCOPE")
 w=await c.get(f"/plans/v1/plans/{P}/workouts/{DATE1}/{DATE2}")
 n=await c.get(f"/plans/v1/plans/{P}/calendarNote/{DATE1}/{DATE2}")
 must(not w.is_error and not n.is_error and len(w.data)==6,"LAB_W_READ")
 return w.data,dig(n.data)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data();must(me.get("personId")==OWNER,"OWNER")
  before,note=await read(c)
  original=next((w for w in before if w.get("workoutId")==WID),None)
  must(original is not None and original.get("workoutTypeValueId")==3,"LAB_WORKOUT")
  r=await c.get("/exerciselibrary/v2/libraries/3892602/items")
  must(not r.is_error and isinstance(r.data,list),"LIB")
  template=next((x for x in r.data if x.get("exerciseLibraryItemId")==14963093),None)
  must(template is not None and template.get("structure"),"TEMPLATE")
  patch=dict(original);patch["structure"]=json.loads(json.dumps(template["structure"]))
  hit=[s for g in patch["structure"]["structure"] for s in g["steps"] if s.get("intensityClass")=="active" and not s.get("targets")]
  must(len(hit)==1,"EMPTY_ACTIVE")
  hit[0]["targets"]=[{"minValue":2,"maxValue":4}]
  patch["structure"].pop("polyline",None)
  state={"modified":False,"restored":False}
  try:
   put=await c._request("PUT",f"/plans/v1/plans/{P}/workouts/{WID}",json=patch,_retry_on_401=False)
   state["modified"]=True
   now,nn=await read(c)
   x=next(y for y in now if y["workoutId"]==WID)
   tgt=[s["targets"] for g in x["structure"]["structure"] for s in g["steps"] if s["intensityClass"]=="active"]
   poly=x["structure"].get("polyline")
   print(json.dumps({"stage":"CANARY_RESULT","write_error":put.is_error,
     "target_saved":tgt==[[{"minValue":2,"maxValue":4}]],"polyline_regenerated":isinstance(poly,list) and len(poly)>0,
     "polyline_length":len(poly or []),"notes_unchanged":nn==note,
     "other_workouts_unchanged":dig([y for y in now if y["workoutId"]!=WID])==dig([y for y in before if y["workoutId"]!=WID])}),flush=True)
  finally:
   current,_=await read(c)
   hit=next((v for v in current if v.get("workoutId")==WID),None)
   must(hit is not None,"LAB_RESTORE_MISSING")
   if {k:v for k,v in hit.items() if k!="lastModifiedDate"}!={k:v for k,v in original.items() if k!="lastModifiedDate"}:
    fix=await c._request("PUT",f"/plans/v1/plans/{P}/workouts/{WID}",json=original,_retry_on_401=False)
    must(not fix.is_error,"LAB_RESTORE_FAILED")
   after,notes2=await read(c)
   restored=next((v for v in after if v.get("workoutId")==WID),None)
   must({k:v for k,v in restored.items() if k!="lastModifiedDate"}=={k:v for k,v in original.items() if k!="lastModifiedDate"} and notes2==note,"RESTORE_DRIFT")
   print(json.dumps({"stage":"LAB_RESTORED","success":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP","error":str(e)[:220]}),flush=True);raise
