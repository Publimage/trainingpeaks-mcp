"""READ-ONLY probe of TrainingPeaks /plans/v1/plansWithAccess hierarchy."""
from __future__ import annotations
import asyncio,json
from tp_mcp.client import TPClient

def summarize(value,depth=0):
 if depth>4:return type(value).__name__
 if isinstance(value,dict):
  return {k:summarize(v,depth+1) for k,v in value.items()
          if any(t in k.lower() for t in ("plan","folder","group","parent","access","title","name","id","child"))}
 if isinstance(value,list):
  return [summarize(x,depth+1) for x in value[:12]]
 return value

async def main()->int:
 async with TPClient() as c:
  me=await c._get_user_data()
  if not isinstance(me,dict) or me.get("personId")!=2116886:
   print(json.dumps({"stage":"STOP_OWNER","writes":0}));return 2
  r=await c.get("/plans/v1/plansWithAccess")
  if r.is_error:
   print(json.dumps({"stage":"READ_ERROR","code":r.error_code.value if r.error_code else None,"message":r.message,"writes":0}));return 3
  data=r.data
  print(json.dumps({
   "stage":"PLANS_WITH_ACCESS_READ",
   "type":type(data).__name__,
   "top_keys":sorted(data.keys()) if isinstance(data,dict) else None,
   "list_count":len(data) if isinstance(data,list) else None,
   "summary":summarize(data),
   "writes":0,
  },ensure_ascii=False)[:28000],flush=True)
 return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
