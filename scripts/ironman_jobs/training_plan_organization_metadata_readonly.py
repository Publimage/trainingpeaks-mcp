"""READ ONLY: inspect TrainingPeaks native Training Plan organization metadata.

Known read endpoints only. No POST/PUT/PATCH/DELETE. Prints structural metadata
and folder/group/library-like fields, never email/token/cookie values.
"""
from __future__ import annotations
import asyncio, json, re
from typing import Any
from tp_mcp.client import TPClient

OWNER=2116886
TARGETS={684762,684463,684555,684543,684484,684206,679801,684602,685173}
SENSITIVE=re.compile(r"(email|token|cookie|secret|password|author)",re.I)
ORG=re.compile(r"(folder|group|library|parent|category|collection|container|sort|order)",re.I)

def clean(value: Any):
    if isinstance(value, dict):
        out={}
        for k,v in value.items():
            if SENSITIVE.search(str(k)):
                out[k]="<redacted>"
            elif ORG.search(str(k)) or k in {"planId","title","isPublic","price","workoutCount","weekCount"}:
                if isinstance(v,(dict,list)):
                    out[k]=shape(v)
                else:
                    out[k]=v
        return out
    return value

def shape(value: Any):
    if isinstance(value,dict):
        return {"type":"dict","keys":sorted(value)}
    if isinstance(value,list):
        return {"type":"list","count":len(value),"sample_shapes":[shape(x) for x in value[:3]]}
    return {"type":type(value).__name__}

def summarize_list(data: Any):
    result={"shape":shape(data)}
    if isinstance(data,list):
        rows=[]
        for p in data:
            if not isinstance(p,dict): continue
            pid=p.get("planId",p.get("id"))
            if pid in TARGETS or any(ORG.search(str(k)) for k in p):
                rows.append({"plan_id":pid,"keys":sorted(p),"org":clean(p)})
        result["selected"]=rows
    elif isinstance(data,dict):
        result["top_keys"]=sorted(data)
        result["org"]=clean(data)
        for k,v in data.items():
            if isinstance(v,list) and ("plan" in k.lower() or "folder" in k.lower()):
                result[f"{k}_shape"]=shape(v)
                selected=[]
                for p in v:
                    if isinstance(p,dict):
                        pid=p.get("planId",p.get("id"))
                        if pid in TARGETS or any(ORG.search(str(x)) for x in p):
                            selected.append({"plan_id":pid,"keys":sorted(p),"org":clean(p)})
                result[f"{k}_selected"]=selected
    return result

async def main():
    async with TPClient() as c:
        me=await c._get_user_data()
        if not isinstance(me,dict) or me.get("personId")!=OWNER:
            print(json.dumps({"stage":"STOP_OWNER","writes":0}));return 2
        for endpoint in ("/plans/v1/plans","/plans/v1/plansWithAccess"):
            r=await c.get(endpoint)
            print(json.dumps({
                "stage":"ENDPOINT_READ",
                "endpoint":endpoint,
                "is_error":bool(r.is_error),
                "status_code":getattr(r,"status_code",None),
                "message":str(r.message)[:160] if r.is_error else None,
                "summary":summarize_list(r.data) if not r.is_error else None,
                "writes":0,
            },ensure_ascii=False),flush=True)
        for pid in sorted(TARGETS):
            r=await c.get(f"/plans/v1/plans/{pid}")
            if r.is_error or not isinstance(r.data,dict):
                print(json.dumps({"stage":"DETAIL_READ_FAIL","plan_id":pid,"writes":0}),flush=True)
                continue
            p=r.data
            print(json.dumps({
                "stage":"DETAIL_READ",
                "plan_id":pid,
                "keys":sorted(p),
                "org":clean(p),
                "writes":0,
            },ensure_ascii=False),flush=True)
    print(json.dumps({"stage":"COMPLETE","provider_writes":0}),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
