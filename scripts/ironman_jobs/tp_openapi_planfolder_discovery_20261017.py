"""READ-ONLY discovery of TP API metadata/OpenAPI for planfolder routes."""
from __future__ import annotations
import asyncio,json
from tp_mcp.client import TPClient

OWNER=2116886
PATHS=(
 "/swagger/v1/swagger.json",
 "/swagger/swagger.json",
 "/swagger.json",
 "/openapi.json",
 "/api-docs",
 "/docs/swagger.json",
 "/planfolder/swagger/v1/swagger.json",
 "/planfolder/swagger.json",
 "/planfolder/openapi.json",
)

def extract(data):
 if not isinstance(data,dict):return {"type":type(data).__name__}
 paths=data.get("paths")
 if not isinstance(paths,dict):
  return {"keys":sorted(data.keys())[:40]}
 rows={}
 for path,methods in paths.items():
  if "planfolder" in path.lower() or ("folder" in path.lower() and "plan" in path.lower()):
   rows[path]={}
   if isinstance(methods,dict):
    for method,spec in methods.items():
     if method.lower() in {"get","post","put","patch","delete"}:
      item={"summary":spec.get("summary") if isinstance(spec,dict) else None}
      if isinstance(spec,dict):
       item["parameters"]=[{
        "name":p.get("name"),"in":p.get("in"),"required":p.get("required"),
        "schema":p.get("schema")
       } for p in spec.get("parameters",[]) if isinstance(p,dict)][:20]
       body=spec.get("requestBody")
       if isinstance(body,dict):item["requestBody"]=body
      rows[path][method]=item
 return {"matching_paths":rows,"count":len(rows)}

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
    "metadata":None if r.is_error else extract(r.data),
   })
  print(json.dumps({"stage":"TP_OPENAPI_PLANFOLDER_DISCOVERY","rows":rows,"writes":0},ensure_ascii=False)[:30000],flush=True)
 return 0

if __name__=="__main__":raise SystemExit(asyncio.run(main()))
