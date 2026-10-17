"""READ-ONLY bounded probe for TrainingPeaks Training Plan folder GET endpoints."""
from __future__ import annotations
import asyncio,json
from tp_mcp.client import TPClient

OWNER=2116886
PATHS=(
 "/planfolder/v1/folder/all",
 "/plans/v1/planFolders",
 "/plans/v1/trainingPlanFolders",
 "/plans/v1/planFolder",
 "/plans/v1/trainingPlanFolder",
 "/plans/v1/folders",
 "/plans/v1/planFoldersWithAccess",
 "/plans/v1/trainingPlanFoldersWithAccess",
 "/plans/v1/foldersWithAccess",
 f"/plans/v1/planFolders/{OWNER}",
 f"/plans/v1/trainingPlanFolders/{OWNER}",
 f"/plans/v1/folders/{OWNER}",
 f"/plans/v1/coaches/{OWNER}/folders",
 f"/plans/v1/users/{OWNER}/folders",
 f"/plans/v1/planFolders?personId={OWNER}",
 f"/plans/v1/planFolders?ownerPersonId={OWNER}",
 f"/plans/v1/trainingPlanFolders?personId={OWNER}",
 "/plans/v2/planFolders",
 "/plans/v2/trainingPlanFolders",
 "/plans/v2/folders",
 "/plans/v2/planFoldersWithAccess",
)

def shape(data):
 if isinstance(data,list):
  keys=sorted({k for x in data[:12] if isinstance(x,dict) for k in x})
  sample=[]
  for x in data[:5]:
   if isinstance(x,dict):
    sample.append({k:v for k,v in x.items() if any(t in k.lower() for t in ("folder","plan","parent","name","id","access"))})
  return {"type":"list","count":len(data),"keys":keys,"sample":sample}
 if isinstance(data,dict):
  return {"type":"dict","keys":sorted(data.keys()),"sample":{k:v for k,v in data.items() if any(t in k.lower() for t in ("folder","plan","parent","name","id","access"))}}
 return {"type":type(data).__name__}

async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  if not isinstance(me,dict) or me.get("personId")!=OWNER:
   print(json.dumps({"stage":"STOP_OWNER","writes":0}));return 2
  rows=[]
  for path in PATHS:
   r=await c.get(path)
   rows.append({
    "path":path,
    "is_error":r.is_error,
    "error_code":r.error_code.value if r.error_code else None,
    "message":r.message if r.is_error else None,
    "shape":None if r.is_error else shape(r.data),
   })
  print(json.dumps({"stage":"PLAN_FOLDER_GET_PROBE","rows":rows,"writes":0},ensure_ascii=False)[:30000],flush=True)
 return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
