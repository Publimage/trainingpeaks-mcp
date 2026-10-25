"""Authenticated GET-only route-shape probe for TrainingPeaks planfolder service.

Distinguishes candidate resources by raw HTTP status/Allow/body preview.
No POST/PUT/PATCH/DELETE requests are issued.
"""
from __future__ import annotations
import asyncio
import json
import re

from tp_mcp.client import TPClient

OWNER=2116886
CANDIDATES=(
 "/planfolder/v1/folder",
 "/planfolder/v1/folder/0",
 "/planfolder/v1/folder/x",
 "/planfolder/v1/folder/all",
 "/planfolder/v1/folder/plan",
 "/planfolder/v1/folder/plans",
 "/planfolder/v1/folder/plan/0",
 "/planfolder/v1/folder/plans/0",
 "/planfolder/v1/folder/0/plan",
 "/planfolder/v1/folder/0/plans",
 "/planfolder/v1/folder/0/plan/0",
 "/planfolder/v1/folder/0/plans/0",
 "/planfolder/v1/plan",
 "/planfolder/v1/plans",
 "/planfolder/v1/plan/0",
 "/planfolder/v1/plans/0",
 "/planfolder/v1/move",
 "/planfolder/v1/remove",
 "/planfolder/v1/assign",
 "/planfolder/v1/rename",
 "/planfolder/v1/copy",
 "/planfolder/v1/folder/move",
 "/planfolder/v1/folder/remove",
 "/planfolder/v1/folder/assign",
 "/planfolder/v1/folder/rename",
 "/planfolder/v1/folder/copy",
 "/planfolder/v1/folder/moveplan",
 "/planfolder/v1/folder/removeplan",
 "/planfolder/v1/folder/assignplan",
 "/planfolder/v1/folder/moveplans",
 "/planfolder/v1/folder/removeplans",
 "/planfolder/v1/folder/assignplans",
 "/planfolder/v1/commands/moveplan",
 "/planfolder/v1/commands/removeplan",
 "/planfolder/v1/commands/assignplan",
 "/planfolder/v1/commands/createfolder",
 "/planfolder/v1/commands/renamefolder",
 "/planfolder/v1/commands/deletefolder",
)


def preview(text:str)->str:
 text=re.sub(r"\s+"," ",text).strip()
 # avoid reflecting arbitrary auth/debug data; only short provider validation text
 return text[:500]


async def main()->int:
 async with TPClient() as c:
  me=await c._get_user_data()
  if not isinstance(me,dict) or me.get("personId")!=OWNER:
   print(json.dumps({"stage":"STOP_OWNER","writes":0}));return 2
  token=await c._ensure_access_token()
  if not token.success:
   print(json.dumps({"stage":"STOP_AUTH","writes":0}));return 3
  await c._ensure_client()
  assert c._client is not None

  rows=[]
  for endpoint in CANDIDATES:
   await c._throttle()
   r=await c._client.request(
     "GET",
     c.base_url+endpoint,
     headers=c._get_headers(),
   )
   rows.append({
     "endpoint":endpoint,
     "http":r.status_code,
     "allow":r.headers.get("Allow"),
     "content_type":r.headers.get("Content-Type"),
     "body":preview(r.text) if r.status_code!=200 else (
       "JSON_LIST" if r.text.lstrip().startswith("[") else
       "JSON_OBJECT" if r.text.lstrip().startswith("{") else
       preview(r.text)
     ),
   })
  interesting=[x for x in rows if x["http"]!=404]
  print(json.dumps({
    "stage":"PLANFOLDER_GET_ROUTE_SHAPE",
    "candidate_count":len(rows),
    "interesting_count":len(interesting),
    "interesting":interesting,
    "status_counts":{str(code):sum(1 for x in rows if x["http"]==code) for code in sorted({x["http"] for x in rows})},
    "provider_writes":0,
  },ensure_ascii=False),flush=True)
 return 0

if __name__=="__main__":raise SystemExit(asyncio.run(main()))
