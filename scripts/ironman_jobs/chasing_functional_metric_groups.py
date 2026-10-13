"""READ_ONLY: group all RPE BI/RU plan prescriptions by function to avoid guessing percentages."""
import asyncio,json,collections,re
from datetime import date
from tp_mcp.client import TPClient
P=685173; START=date(2027,1,4)
RANGES=[("2027-01-04","2027-02-28"),("2027-03-01","2027-04-25"),("2027-04-26","2027-06-20")]
def relative(w):
 d=date.fromisoformat(str(w["workoutDay"])[:10]);off=(d-START).days
 return (off//7+1,off%7)
def classify(w):
 t=w.get("title","").lower()
 s=w.get("structure") or {}
 steps=[x for g in s.get("structure") or [] for x in g.get("steps") or []]
 names=" ".join(x.get("name","").lower() for x in steps)
 p=t+" "+names
 if "test" in t or "retest" in t:return "TEST_EXCEPTION"
 if any(s in p for s in ["race pace","im pace","ironman pace","im bike","im run","diagnostic","diagnostico","ritmo gara","passo im"]):return "RACE_SPECIFIC"
 if any(s in p for s in ["threshold","soglia","vo2","microinterval","microinterv","over-under","tempo","steady","fartlek","progressiv","intervall"]):return "QUALITY_SPECIFIC"
 if "aero" in p:return "AERO_ENDURANCE"
 if "brick" in t:return "BRICK_EASY"
 if "recupero" in p or "circolazione" in p:return "RECOVERY"
 if "lungo" in t or "fondo lungo" in p:return "LONG_ENDURANCE"
 if any(s in p for s in ["sotto lt1","endurance","fondo","facile","aerobico","agile","attivazione"]):return "EASY_ENDURANCE"
 return "MANUAL_REVIEW"
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  if me.get("personId")!=2116886:raise RuntimeError("OWNER")
  p=await c.get(f"/plans/v1/plans/{P}")
  if p.is_error or p.data.get("isPublic") is not False:raise RuntimeError("SCOPE")
  rows=[]
  for a,b in RANGES:
   x=await c.get(f"/plans/v1/plans/{P}/workouts/{a}/{b}")
   if x.is_error:raise RuntimeError("READ")
   rows+=x.data
  counts=collections.Counter();uniques=collections.defaultdict(dict)
  for w in rows:
   sp=w.get("workoutTypeValueId");mt=(w.get("structure") or {}).get("primaryIntensityMetric")
   if sp not in (2,3) or mt!="rpe":continue
   cl=classify(w);counts[(sp,cl)]+=1
   st=w["structure"]
   n=[(g.get("type"),g.get("length",{}).get("value"),[(z.get("name"),z.get("length",{}).get("value"),z.get("intensityClass")) for z in g.get("steps") or []]) for g in st.get("structure") or []]
   key=(w.get("title"),json.dumps(n))
   item=uniques[(sp,cl)].get(key)
   if item is None:uniques[(sp,cl)][key]={"title":w.get("title"),"ids":[w.get("workoutId")],"relative":[relative(w)],"outline":n}
   else:item["ids"].append(w.get("workoutId"));item["relative"].append(relative(w))
  print(json.dumps({"stage":"CLASSIFIED","counts":{str(k):v for k,v in counts.items()},
   "unique":{str(k):len(v) for k,v in uniques.items()}},ensure_ascii=False),flush=True)
  for k,v in uniques.items():
   print(json.dumps({"stage":"GROUP","sport":k[0],"profile":k[1],
    "entries":[{"title":x["title"],"count":len(x["ids"]),"weeks":[z[0] for z in x["relative"]],"steps":[[z[0],z[1],z[2]] for z in x["outline"]]} for x in v.values()]},ensure_ascii=False),flush=True)
if __name__=="__main__":asyncio.run(main())
