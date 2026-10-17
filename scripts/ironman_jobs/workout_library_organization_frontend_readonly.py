"""READ ONLY: locate exact current Workout Library API-proxy method definitions in public TP JS."""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx

BASE="https://app.trainingpeaks.com/"
METHODS=(
 "copyWorkoutToLibrary","deleteWorkoutFromLibrary","deleteActivityFromLibrary",
 "updateWorkoutInLibrary","updateActivityInLibrary",
 "createWorkoutInLibrary","createWorkoutLibrary","renameWorkoutLibrary",
 "updateWorkoutLibrary","deleteWorkoutLibrary","getWorkoutDetails"
)

def trusted(url):
    h=(urlparse(url).hostname or "").lower()
    return h=="app.trainingpeaks.com" or h.endswith(".trainingpeaks.com")

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
                    for method in METHODS:
                        patterns=(f'key:"{method}"',f"{method}:function",f'"{method}":function')
                        for pat in patterns:
                            for m in list(re.finditer(re.escape(pat),src))[:8]:
                                a,b=max(0,m.start()-1900),min(len(src),m.end()+6200)
                                rows.append({"asset":urlparse(url).path,"method":method,
                                             "pattern":pat,"offset":m.start(),
                                             "context":src[a:b].replace("\n"," ").replace("\r"," ")[:8000]})
                    return rows
                except Exception:return []
        chunks=await asyncio.gather(*(inspect(u) for u in urls))
        rows=[x for chunk in chunks for x in chunk]
        rows.sort(key=lambda x:(x["method"],x["asset"],x["offset"]))
        print(json.dumps({"stage":"SUMMARY","assets":len(urls),"definitions":len(rows),"writes":0}),flush=True)
        for row in rows[:30]:
            print(json.dumps({"stage":"DEF",**row,"writes":0},ensure_ascii=False),flush=True)
        print(json.dumps({"stage":"COMPLETE","provider_writes":0}),flush=True)
        return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
