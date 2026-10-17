"""READ ONLY: inspect current public frontend around native/classic Workout Library routes."""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx
BASE="https://app.trainingpeaks.com/"
TERMS=(
 "LibraryContent/workoutLibrary/items/copy",
 "libraryContent/workoutLibrary",
 "items/copy",
 "ActivityWorkoutTemplate",
 "deleteActivityFromLibrary",
 "onTryMoveWorkoutToLibrary",
 "onCopyWorkoutToLibrary",
 "exerciseLibraryId"
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
                    src=r.text;rows=[]
                    for term in TERMS:
                        for m in list(re.finditer(re.escape(term),src,re.I))[:10]:
                            a,b=max(0,m.start()-2400),min(len(src),m.end()+5200)
                            rows.append({"asset":urlparse(url).path,"term":term,"offset":m.start(),
                                         "context":src[a:b].replace("\n"," ").replace("\r"," ")[:7600]})
                    return rows
                except Exception:return []
        chunks=await asyncio.gather(*(inspect(u) for u in urls))
        rows=[x for ch in chunks for x in ch]
        rows.sort(key=lambda x:(0 if "LibraryContent/workoutLibrary" in x["context"] else 1,x["term"],x["asset"]))
        print(json.dumps({"stage":"SUMMARY","hits":len(rows),"writes":0}),flush=True)
        for row in rows[:24]:
            print(json.dumps({"stage":"HIT",**row,"writes":0},ensure_ascii=False),flush=True)
        print(json.dumps({"stage":"COMPLETE","provider_writes":0}),flush=True)
        return 0
if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
