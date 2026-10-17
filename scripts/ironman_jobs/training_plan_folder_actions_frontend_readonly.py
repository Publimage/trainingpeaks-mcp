"""READ ONLY: inspect the public TrainingPeaks plan-folder action module.

Fetches one public JS asset already identified by the route audit. No auth/writes.
"""
from __future__ import annotations
import asyncio,json,re,httpx
URL="https://app.trainingpeaks.com/release-20261016-83ae3fe/modules-8af7f7d8.js"
TERMS=(
 "GET_FOLDERS","ASSIGN_PLAN_TO_FOLDER","MOVE_PLANS_BETWEEN_FOLDERS",
 "REMOVE_PLANS_FROM_FOLDER","CREATE_FOLDER","RENAME_FOLDER","DELETE_FOLDER",
 "MOVE_PLANS_TO_MY_PLANS"
)

async def main()->int:
    async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
        r=await h.get(URL)
    if r.status_code!=200 or len(r.content)>14000000:
        print(json.dumps({"stage":"STOP","http":r.status_code,"writes":0}));return 2
    src=r.text
    emitted=0
    for term in TERMS:
        hits=list(re.finditer(re.escape(term),src))
        for m in hits[:4]:
            a,b=max(0,m.start()-2200),min(len(src),m.end()+4200)
            ctx=src[a:b].replace("\n"," ").replace("\r"," ")
            # Keep only contexts that look like action/api code, not translations.
            if any(x in ctx for x in (".get(", ".post(", ".put(", ".delete(", "axios", "fetch(", "/plans", "actionNames")):
                print(json.dumps({"stage":"HIT","term":term,"offset":m.start(),"context":ctx[:6500],"writes":0},ensure_ascii=False),flush=True)
                emitted+=1
                if emitted>=12:break
        if emitted>=12:break
    print(json.dumps({"stage":"COMPLETE","hits":emitted,"provider_writes":0}),flush=True)
    return 0
if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
