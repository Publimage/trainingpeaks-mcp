"""Read-only note attachment inventory. Never output temporary presigned URL."""
import asyncio,json
from tp_mcp.client import TPClient
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  assert me.get("personId")==2116886
  for plan,first,last,nid in [
   (684484,"2027-07-05","2027-07-12",2655001),
   (684602,"2026-10-05","2027-04-01",2653899)]:
   r=await c.get(f"/plans/v1/plans/{plan}/calendarNote/{first}/{last}")
   print("NOTE_GET",plan,"ok",not r.is_error,flush=True)
   assert not r.is_error and isinstance(r.data,list)
   n=next((x for x in r.data if x.get("id")==nid),None)
   assert n is not None
   atts=n.get("attachments") or []
   print("NOTE",plan,"note",nid,"keys",list(n.keys()),
         "attachments",len(atts),"attachment_details",[
            {"id":a.get("id"),"filename":a.get("fileName"),"size":a.get("contentLength")}
            for a in atts],"description_prefix",str(n.get("description",""))[:15],
         "desc_len",len(str(n.get("description",""))),flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
