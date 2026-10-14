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
  b=Counter((x["sp"],x["metric"],z["cl"],z["n"]) for x in out for z in x["steps"])
  selected=[x for x in out if x["metric"]=="rpe" and (x["sp"]==2 and any(any(k in (z["n"] or "").lower() for k in ("pace","tempo","aero","soglia","steady","rpe gara")) for z in x["steps"]) or x["sp"]==3 and (any(any(k in (z["n"] or "").lower() for k in ("pace","gara","veloce","test","transizione","scioltezza")) for z in x["steps"]) or "test" in x["t"].lower()))]
  print(json.dumps({"metrics":{str(k):v for k,v in a.items()},
    "special":[{"w":x["wk"],"id":x["id"],"sp":x["sp"],"t":x["t"],"steps":[{"n":z["n"],"cl":z["cl"],"t":z["tg"]} for z in x["steps"] if any(k in (z["n"] or "").lower() for k in ("pace","tempo","aero","soglia","steady","gara","veloce","test","transizione","scioltezza"))]} for x in selected],
    "rpe_run_titles":[{"w":x["wk"],"id":x["id"],"t":x["t"]} for x in out if x["metric"]=="rpe" and x["sp"]==3 and any(k in x["t"].lower() for k in ("specifico","test","brick","attivazione"))],
    "percent_bi":[{"w":x["wk"],"id":x["id"],"t":x["t"],"steps":[{"n":z["n"],"t":z["tg"]} for z in x["steps"] if "pace" in (z["n"] or "").lower()]} for x in out if x["sp"]==2 and x["metric"]=="percentOfFtp"]},ensure_ascii=False),flush=True)
if __name__=="__main__":asyncio.run(main())
