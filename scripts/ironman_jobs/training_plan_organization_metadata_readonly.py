"""READ ONLY: inspect TrainingPeaks native Training Plan organization metadata.

Known read endpoints only. No POST/PUT/PATCH/DELETE. Compact output is designed
for the IRONMAN operator log limit.
"""
from __future__ import annotations
import asyncio, json, re
from typing import Any
from tp_mcp.client import TPClient

OWNER=2116886
TARGETS={684762,684463,684555,684543,684484,684206,679801,684602,685173}
ORG=re.compile(r"(folder|group|library|parent|category|collection|container|sort|order)",re.I)

def shape(v: Any):
    if isinstance(v,dict): return {"type":"dict","keys":sorted(v)}
    if isinstance(v,list): return {"type":"list","count":len(v)}
    return {"type":type(v).__name__}

def plan_rows(items):
    rows=[]
    for p in items if isinstance(items,list) else []:
        if not isinstance(p,dict): continue
        pid=p.get("planId",p.get("id"))
        if pid in TARGETS:
            org={k:v for k,v in p.items() if ORG.search(str(k)) and not isinstance(v,(dict,list))}
            rows.append({"id":pid,"title":p.get("title"),"org":org,"keys":sorted(p)})
    return rows

async def main():
    async with TPClient() as c:
        me=await c._get_user_data()
        if not isinstance(me,dict) or me.get("personId")!=OWNER:
            print(json.dumps({"stage":"STOP_OWNER","writes":0}));return 2

        for endpoint in ("/plans/v1/plans","/plans/v1/plansWithAccess"):
            r=await c.get(endpoint)
            if r.is_error:
                print(json.dumps({"stage":"ENDPOINT","endpoint":endpoint,"error":True,
                                  "status":getattr(r,"status_code",None),"writes":0}),flush=True)
                continue
            data=r.data
            out={"stage":"ENDPOINT","endpoint":endpoint,"error":False,
                 "shape":shape(data),"writes":0}
            if isinstance(data,list):
                out["union_keys"]=sorted({k for x in data if isinstance(x,dict) for k in x})
                out["org_keys"]=sorted({k for x in data if isinstance(x,dict) for k in x if ORG.search(k)})
                out["targets"]=plan_rows(data)
            elif isinstance(data,dict):
                out["top_keys"]=sorted(data)
                out["org_top_keys"]=sorted(k for k in data if ORG.search(k))
                for k,v in data.items():
                    if isinstance(v,list):
                        out["list_"+k]={"count":len(v),
                                        "union_keys":sorted({kk for x in v if isinstance(x,dict) for kk in x}),
                                        "org_keys":sorted({kk for x in v if isinstance(x,dict) for kk in x if ORG.search(kk)}),
                                        "targets":plan_rows(v)}
            print(json.dumps(out,ensure_ascii=False),flush=True)

        # One lab plan detail is enough to prove detail endpoint semantics.
        r=await c.get("/plans/v1/plans/684484")
        if not r.is_error and isinstance(r.data,dict):
            p=r.data
            print(json.dumps({"stage":"DETAIL_684484","keys":sorted(p),
                              "org_keys":sorted(k for k in p if ORG.search(k)),
                              "org_values":{k:v for k,v in p.items() if ORG.search(k) and not isinstance(v,(dict,list))},
                              "writes":0},ensure_ascii=False),flush=True)

    print(json.dumps({"stage":"COMPLETE","provider_writes":0}),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
