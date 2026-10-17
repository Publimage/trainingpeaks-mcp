"""READ ONLY: locate TrainingPeaks coachTrainingPlans API-proxy methods in public JS.

Scans public release JS for exact method names and emits only request-like contexts.
No authentication and no provider writes.
"""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx

BASE="https://app.trainingpeaks.com/"
TERMS=("movePlansBetweenFolders","assignPlanToFolder","removePlansFromFolder",
       "renameFolder","createFolder","deleteFolder","getFolders")

def trusted(url):
    host=(urlparse(url).hostname or "").lower()
    return host=="app.trainingpeaks.com" or host.endswith(".trainingpeaks.com")

async def main()->int:
    async with httpx.AsyncClient(timeout=22,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
        page=await h.get(BASE)
        if page.status_code!=200:return 2
        urls=re.findall(r"""<script[^>]+src=['"]([^'"]+)""",page.text,re.I)
        urls=list(dict.fromkeys(urljoin(BASE,u) for u in urls if ".js" in u and "release-" in u and trusted(urljoin(BASE,u))))[:180]
        sem=asyncio.Semaphore(8)
        async def inspect(url):
            async with sem:
                try:
                    r=await h.get(url)
                    if r.status_code!=200 or len(r.content)>14000000:return []
                    src=r.text; rows=[]
                    for term in TERMS:
                        hits=list(re.finditer(re.escape(term),src))
                        for idx,m in enumerate(hits[:12]):
                            a,b=max(0,m.start()-1800),min(len(src),m.end()+3800)
                            ctx=src[a:b].replace("\n"," ").replace("\r"," ")
                            requestish=any(x in ctx for x in (
                                "/plans/","apiRoot","apiProxy","request(",".get(",".post(",".put(",".delete(",
                                "fetch(","axios","http"))
                            if requestish:
                                rows.append({"asset":urlparse(url).path,"term":term,"occurrence":idx,
                                             "offset":m.start(),"context":ctx[:5600]})
                    return rows
                except Exception:return []
        chunks=await asyncio.gather(*(inspect(u) for u in urls))
        rows=[x for chunk in chunks for x in chunk]
        print(json.dumps({"stage":"SUMMARY","assets":len(urls),"hits":len(rows),"writes":0}),flush=True)
        # Prefer contexts containing explicit plan paths or HTTP-looking methods.
        rows.sort(key=lambda x:(0 if "/plans/" in x["context"] else 1,
                                0 if any(y in x["context"] for y in (".post(",".put(",".delete(",".get(")) else 1,
                                x["term"],x["asset"],x["offset"]))
        for row in rows[:24]:
            print(json.dumps({"stage":"HIT",**row,"writes":0},ensure_ascii=False),flush=True)
        print(json.dumps({"stage":"COMPLETE","provider_writes":0}),flush=True)
        return 0
if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
