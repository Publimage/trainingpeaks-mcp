"""Public-only TrainingPeaks main UI JS: find native Strength Save-To-Library route.

Strict GET only; no login, no bearer, no provider modifications, no HAR.
Print bounded 650-char neighborhoods for selected identifiers in public bundle.
"""
from __future__ import annotations
import asyncio,json,re,httpx

URL="https://app.trainingpeaks.com/release-20261009-47467f9/modules-f765ba67.js"
TERMS=("onAddWorkoutToLibrary",)

def spans(src:str,term:str,limit:int=60)->list[dict]:
    result=[]
    for m in list(re.finditer(re.escape(term),src,re.I))[:limit]:
        a,b=max(0,m.start()-3600),min(len(src),m.end()+900)
        result.append({"pos":m.start(),"context":src[a:b].replace("\n"," ")})
    return result

async def main()->int:
    async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
        r=await h.get(URL)
    if r.status_code!=200 or len(r.content)>6_000_000:
        print(json.dumps({"http":r.status_code,"len":len(r.content),"stop":True}));return 2
    source=r.content.decode("utf-8","replace")
    print(json.dumps({"source":URL,"bytes":len(source),"read_only":True}),flush=True)
    for word in TERMS:
        hits=spans(source,word)[-1:]
        if hits:
            print(json.dumps({"term":word,"count":len(list(re.finditer(re.escape(word),source,re.I))),
                              "hits":hits},ensure_ascii=False),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
