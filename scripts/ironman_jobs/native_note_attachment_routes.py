"""Read-only scan of conservative candidate Training Plan native-note attachment GET routes."""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=684602
NOTE=2653899
LAB=684484
ROUTES=[
 f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}",
 f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/attachments",
 f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/attachment",
 f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/files",
 f"/plans/v1/plans/{PLAN}/calendarNotes/{NOTE}/attachments",
 f"/plans/v1/plans/{PLAN}/attachments",
 f"/plans/v1/plans/{PLAN}/calendarNote/attachments",
 f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/upload",
 f"/files/v1/attachments",
 f"/files/v1/attachments/95193",
 f"/attachments/v1/attachments",
 f"/attachments/v1/attachments/95193",
 f"/file/v1/attachments",
 f"/fitness/v6/attachments",
]
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  assert isinstance(me,dict) and me.get("personId")==OWNER,"Wrong owner"
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  assert not p.is_error and p.data["title"]=="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
  assert p.data["workoutCount"]==259 and p.data["isPublic"] is False
  n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2026-10-05/2027-04-01")
  assert not n.is_error and len(n.data)==35
  for path in ROUTES:
   result=await c.get(path)
   data=result.data
   typ=type(data).__name__
   shape=(list(data.keys())[:15] if isinstance(data,dict) else len(data) if isinstance(data,list) else None)
   print(json.dumps({"path":path,"ok":not result.is_error,
     "code":str(result.error_code) if result.is_error else None,
     "type":typ,"shape":shape}),flush=True)
  print("PROVIDER_WRITES:0",flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
