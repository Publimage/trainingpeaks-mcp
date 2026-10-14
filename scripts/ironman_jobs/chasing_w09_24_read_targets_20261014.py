"""READ-ONLY inspect W09-24 native bike/run roles to select strictly safe FTP/threshold targets."""
import asyncio,json
from datetime import date
from tp_mcp.client import TPClient
RANGES=(("2027-03-01","2027-04-25"),("2027-04-26","2027-06-20"))
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  if u.get("personId")!=2116886:raise RuntimeError("OWNER")
  p=await c.get("/plans/v1/plans/685173")
  if p.is_error or p.data.get("isPublic") is not False or p.data.get("workoutCount")!=276:raise RuntimeError("PLAN")
  rows=[]
  for a,b in RANGES:
   q=await c.get(f"/plans/v1/plans/685173/workouts/{a}/{b}")
   if q.is_error or not isinstance(q.data,list):raise RuntimeError("READ")
   rows+=q.data
  out=[]
  for w in rows:
   if w.get("workoutTypeValueId") not in (2,3):continue
   s=w.get("structure") or {}
   d=(date.fromisoformat(str(w["workoutDay"])[:10])-date(2027,1,4)).days
   out.append({"wk":d//7+1,"wd":d%7,"id":w["workoutId"],"sp":w["workoutTypeValueId"],
    "t":w.get("title"),"metric":s.get("primaryIntensityMetric"),
    "steps":[{"n":z.get("name"),"cl":z.get("intensityClass"),"d":z.get("length",{}).get("value"),
      "tg":z.get("targets",[])} for g in s.get("structure") or [] for z in g.get("steps") or []]})
  from collections import Counter
  a=Counter((x["sp"],x["metric"]) for x in out)
  groups=Counter()
  unexpected=[];plus=[];race=[]
  for x in out:
   names=[z["n"] or "" for z in x["steps"]]
   if x["sp"]==2 and any("pace+" in n.lower() or "pace +" in n.lower() for n in names):plus.append({"wk":x["wk"],"id":x["id"],"names":names})
   if x["sp"]==2 and any("im pace" in n.lower() or "ironman pace" in n.lower() for n in names):race.append({"wk":x["wk"],"id":x["id"],"metric":x["metric"],"steps":[{"n":z["n"],"c":z["cl"],"t":z["tg"]} for z in x["steps"]]})
   if x["metric"]=="rpe":
    types=set((z["cl"],z["n"]) for z in x["steps"])
    groups[(x["sp"],tuple(sorted(z["cl"] or "" for z in x["steps"])))]+=1
    for z in x["steps"]:
     if not z["tg"]:unexpected.append({"id":x["id"],"wk":x["wk"],"sp":x["sp"],"name":z["n"],"cl":z["cl"]})
  print(json.dumps({"count":len(out),"metrics":{str(k):v for k,v in a.items()},"plus":plus,"race":race,"empty":unexpected,"step_names":sorted(set(z["n"] or "" for x in out if x["metric"]=="rpe" for z in x["steps"]))},ensure_ascii=False),flush=True)
if __name__=="__main__":asyncio.run(main())
