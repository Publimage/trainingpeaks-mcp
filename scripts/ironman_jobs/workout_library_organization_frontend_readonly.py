"""READ ONLY: inspect current public Workout Library MOVE use-case, including ActivityWorkoutTemplate branching."""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx
BASE="https://app.trainingpeaks.com/"
TERMS=("MOVE_WORKOUT_TO_LIBRARY","TRY_MOVE_WORKOUT_TO_LIBRARY","moveWorkoutToLibrary",
       "ACTIVITY_WORKOUT_TEMPLATE","ActivityWorkoutTemplate","onPromptMoveToLibrary")
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
                        for m in list(re.finditer(re.escape(term),src,re.I))[:20]:
                            a,b=max(0,m.start()-4200),min(len(src),m.end()+6200)
                            ctx=src[a:b].replace("\n"," ").replace("\r"," ")
                            if ("moveWorkoutToLibrary" in ctx or "MOVE_WORKOUT_TO_LIBRARY" in ctx) and (
                                "ActivityWorkoutTemplate" in ctx or "ACTIVITY_WORKOUT_TEMPLATE" in ctx):
                                rows.append({"asset":urlparse(url).path,"term":term,"offset":m.start(),"context":ctx[:9800]})
                    return rows
                except Exception:return []
        chunks=await asyncio.gather(*(inspect(u) for u in urls))
        rows=[x for ch in chunks for x in ch]
        # dedupe contexts by asset+offset neighborhood
        seen=set();out=[]
        for x in rows:
            key=(x["asset"],x["offset"]//500)
            if key in seen:continue
            seen.add(key);out.append(x)
        print(json.dumps({"stage":"SUMMARY","hits":len(out),"writes":0}),flush=True)
        for row in out[:14]:
            print(json.dumps({"stage":"MOVE_CONTEXT",**row,"writes":0},ensure_ascii=False),flush=True)
        print(json.dumps({"stage":"COMPLETE","provider_writes":0}),flush=True)
        return 0
if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
