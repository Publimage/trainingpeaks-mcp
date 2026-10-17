"""READ ONLY: discover TrainingPeaks Training Plan folder frontend routes.

Public app HTML/JS GET only. No authentication and no provider writes.
Print bounded route-adjacent snippets for plan folder identifiers.
"""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx

BASE="https://app.trainingpeaks.com/"
TERMS=(
    "plansWithAccess","planFolder","planFolders","trainingPlanFolder",
    "trainingPlanFolders","folderId","createFolder","renameFolder","deleteFolder",
    "movePlan","copyPlan","/plans/v1/"
)

def trusted(url:str)->bool:
    host=(urlparse(url).hostname or "").lower()
    return host=="app.trainingpeaks.com" or host.endswith(".trainingpeaks.com")

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
        print(json.dumps({"stage":"INDEX","asset_count":len(urls),"writes":0}),flush=True)
        sem=asyncio.Semaphore(8)
        async def inspect(url):
            async with sem:
                try:
                    r=await h.get(url)
                    if r.status_code!=200:
                        return None
                    if len(r.content)>14000000:
                        return None
                    body=r.text
                    hits=[]
                    for term in TERMS:
                        mm=list(re.finditer(re.escape(term),body,re.I))
                        for m in mm[:4]:
                            a,b=max(0,m.start()-420),min(len(body),m.end()+900)
                            s=body[a:b].replace("\n"," ").replace("\r"," ")
                            hits.append({"term":term,"context":s[:1400]})
                    return {"asset":urlparse(url).path,"hits":hits} if hits else None
                except Exception:
                    return None
        results=await asyncio.gather(*(inspect(u) for u in urls))
        matched=[x for x in results if x]
        print(json.dumps({"stage":"SUMMARY","scanned":len(urls),"matched_assets":len(matched),"writes":0}),flush=True)
        emitted=0
        for row in matched:
            # Keep operator output bounded.
            for hit in row["hits"]:
                print(json.dumps({"stage":"HIT","asset":row["asset"],**hit,"writes":0},ensure_ascii=False),flush=True)
                emitted+=1
                if emitted>=28:
                    break
            if emitted>=28:
                break
        print(json.dumps({"stage":"COMPLETE","hits_emitted":emitted,"provider_writes":0}),flush=True)
        return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
