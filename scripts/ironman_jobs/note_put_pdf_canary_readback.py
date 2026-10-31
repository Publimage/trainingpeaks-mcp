"""Inspect only PDF-preserving PUT lab canary, no provider write."""
import asyncio,json
from tp_mcp.client import TPClient
async def main():
 async with TPClient() as c:
  me=await c._get_user_data();assert me.get("personId")==2116886
  p=await c.get("/plans/v1/plans/684484");assert not p.is_error and p.data.get("workoutCount")==1
  r=await c.get("/plans/v1/plans/684484/calendarNote/2027-07-05/2027-07-12")
  assert not r.is_error and isinstance(r.data,list) and len(r.data)==2
  note=next(n for n in r.data if n.get("id")==2655235)
  anchor=next(n for n in r.data if n.get("id")==2651317)
  print("POST_PUT_CANARY_POSTFLIGHT",json.dumps({
    "id":note.get("id"),"title":note.get("title"),
    "body_updated":note.get("description")=="Disposable protected Note with binary PDF. The athlete guide must be read first.",
    "date":note.get("noteDate"),"planId":note.get("planId"),
    "fields":list(note.keys()),
    "attachments":[{"id":a.get("id"),"name":a.get("fileName"),"size":a.get("contentLength")} for a in note.get("attachments",[])],
    "anchor_preserved":anchor.get("title")=="[MCP TEST] DELETE PROBE | Monday anchor note",
    "provider_writes":0},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
