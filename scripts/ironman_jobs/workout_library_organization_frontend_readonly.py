"""READ ONLY: extract all current public frontend route strings around native Strength Workout Library."""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx

BASE="https://app.trainingpeaks.com/"
NEEDLES=("workoutLibrary","LibraryContent","ActivityWorkoutTemplate","/rx/activity/v1/")

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
                    # Quoted literals likely to be URL/path fragments.
                    for m in re.finditer(r"""['"]([^'"]{0,420})['"]""",src):
                        value=m.group(1)
                        low=value.lower()
                        if ("workoutlibrary" in low or "/rx/activity/v1/" in low or
                            "librarycontent" in low):
                            if value not in [x["value"] for x in rows]:
                                rows.append({"asset":urlparse(url).path,"offset":m.start(),"value":value[:500]})
                    # Context around delete/move words when native-library terms are nearby.
                    for term in ("delete","remove","move","copy"):
                        for m in list(re.finditer(term,src,re.I))[:800]:
                            a,b=max(0,m.start()-1200),min(len(src),m.end()+1600)
                            ctx=src[a:b]
                            if any(n.lower() in ctx.lower() for n in NEEDLES):
                                rows.append({"asset":urlparse(url).path,"offset":m.start(),
                                             "value":"CTX:"+ctx.replace("\n"," ").replace("\r"," ")[:2600]})
                                if len(rows)>=70:break
                    return rows[:70]
                except Exception:return []
        chunks=await asyncio.gather(*(inspect(u) for u in urls))
        rows=[x for ch in chunks for x in ch]
        # de-duplicate by value
        seen=set(); uniq=[]
        for x in rows:
            k=x["value"]
            if k in seen:continue
            seen.add(k);uniq.append(x)
        uniq.sort(key=lambda x:(0 if "/rx/" in x["value"].lower() else 1,
                                0 if any(w in x["value"].lower() for w in ("delete","remove","move")) else 1,
                                x["asset"],x["offset"]))
        print(json.dumps({"stage":"SUMMARY","assets":len(urls),"hits":len(uniq),"writes":0}),flush=True)
        for row in uniq[:45]:
            print(json.dumps({"stage":"ROUTE_OR_CONTEXT",**row,"writes":0},ensure_ascii=False),flush=True)
        print(json.dumps({"stage":"COMPLETE","provider_writes":0}),flush=True)
        return 0
if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
