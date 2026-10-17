"""READ ONLY: extract TrainingPeaks Training Plan folder API routes from public frontend JS.

Public app HTML/JS GET only. No auth and no provider writes.
"""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx

BASE="https://app.trainingpeaks.com/"
IDENTIFIERS=(
 "getTrainingPlanFolders","createTrainingPlanFolder","renameTrainingPlanFolder",
 "deleteTrainingPlanFolder","movePlanToFolder","removePlanFromFolder",
 "UnableToMovePlanToFolder","UnableToGetTrainingPlanFolders"
)

def trusted(url:str)->bool:
    host=(urlparse(url).hostname or "").lower()
    return host=="app.trainingpeaks.com" or host.endswith(".trainingpeaks.com")

def route_strings(body:str):
    out=[]
    # Quoted string fragments that actually contain a /plans/... route.
    for m in re.finditer(r"""['"]([^'"]{0,220}/plans/[^'"]{0,260})['"]""",body,re.I):
        s=m.group(1)
        if s not in out: out.append(s)
    return out[:120]

async def main()->int:
    async with httpx.AsyncClient(timeout=22,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
        page=await h.get(BASE)
        if page.status_code!=200:
            print(json.dumps({"stage":"STOP_INDEX","http":page.status_code,"writes":0}));return 2
        urls=re.findall(r"""<script[^>]+src=['"]([^'"]+)""",page.text,re.I)
        urls=list(dict.fromkeys(
            urljoin(BASE,u) for u in urls
            if ".js" in u and "release-" in u and trusted(urljoin(BASE,u))
        ))[:180]
        sem=asyncio.Semaphore(8)
        async def inspect(url):
            async with sem:
                try:
                    r=await h.get(url)
                    if r.status_code!=200 or len(r.content)>14000000:return None
                    body=r.text
                    routes=route_strings(body)
                    code=[]
                    for ident in IDENTIFIERS:
                        for m in list(re.finditer(re.escape(ident),body,re.I))[:8]:
                            a,b=max(0,m.start()-900),min(len(body),m.end()+1800)
                            ctx=body[a:b].replace("\n"," ").replace("\r"," ")
                            # Ignore translation-only neighborhoods.
                            if "/plans/" in ctx or ".get(" in ctx or ".post(" in ctx or ".put(" in ctx or ".delete(" in ctx:
                                code.append({"identifier":ident,"context":ctx[:2800]})
                    return {"asset":urlparse(url).path,"routes":routes,"code":code} if routes or code else None
                except Exception:return None
        results=await asyncio.gather(*(inspect(u) for u in urls))
        matched=[x for x in results if x]
        print(json.dumps({"stage":"SUMMARY","assets":len(urls),"matched":len(matched),"writes":0}),flush=True)
        routes=[]
        for x in matched:
            for path in x["routes"]:
                key=(x["asset"],path)
                if key not in routes: routes.append(key)
        for asset,path in routes[:80]:
            print(json.dumps({"stage":"ROUTE","asset":asset,"path":path,"writes":0},ensure_ascii=False),flush=True)
        emitted=0
        for x in matched:
            for hit in x["code"]:
                print(json.dumps({"stage":"CODE","asset":x["asset"],**hit,"writes":0},ensure_ascii=False),flush=True)
                emitted+=1
                if emitted>=20:break
            if emitted>=20:break
        print(json.dumps({"stage":"COMPLETE","route_count":len(routes),"code_hits":emitted,"provider_writes":0}),flush=True)
        return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
