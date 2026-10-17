"""READ ONLY: characterize plan author/email metadata after title-only PUT.
Print no email or secrets: presence/type/digest only.
"""
import asyncio,hashlib,json
from tp_mcp.client import TPClient
OWNER=2116886
PLANS=[684602,679801,684463,684484,684206,504281]
def sig(s):
 if s is None:return "NONE"
 return hashlib.sha256(str(s).encode()).hexdigest()[:12]
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  assert isinstance(me,dict) and me.get("personId")==OWNER
  for i in PLANS:
   r=await c.get(f"/plans/v1/plans/{i}")
   assert not r.is_error and isinstance(r.data,dict) and r.data.get("planId")==i
   p=r.data
   x={k:{"present":p.get(k) not in (None,""),"type":type(p.get(k)).__name__,
         "digest":sig(p.get(k))} for k in ("author","planEmail")}
   print(json.dumps({"id":i,"title":p.get("title"),"metadata":x,
      "isPublic":p.get("isPublic"),"workoutCount":p.get("workoutCount")}),flush=True)
  print("NO_PROVIDER_WRITES")
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
