"""Public-only TrainingPeaks main UI JS: find native Strength Save-To-Library route.

Strict GET only; no login, no bearer, no provider modifications, no HAR.
Print bounded 650-char neighborhoods for selected identifiers in public bundle.
"""
from __future__ import annotations
import asyncio,json,re,httpx

URL="https://app.trainingpeaks.com/release-20261009-47467f9/modules-23bb80da.js"
TERMS=("onAddWorkoutToLibrary",)

def spans(src:str,term:str,limit:int=60)->list[dict]:
    result=[]
    for m in list(re.finditer(re.escape(term),src,re.I))[:limit]:
        a,b=max(0,m.start()-3600),min(len(src),m.end()+900)
        result.append({"pos":m.start(),"context":src[a:b].replace("\n"," ")})
    return result

async def main()->int:
    async with httpx.AsyncClient(timeout=20,follow_redirects=False) as h:
        response=await h.get(URL)
    if response.status_code!=200 or len(response.content)>1000000:
        print(json.dumps({"status":"STOP","http":response.status_code}),flush=True)
        return 2
    source=response.text
    print(json.dumps({"bytes":len(source),"read_only":True}),flush=True)
    for term in ("copyCalendarActivityToLibrary","createFromWorkout","workoutLibraryItemType",
                 "LibraryContent","_v1BaseUrl"):
        matches=list(re.finditer(re.escape(term),source,re.I))
        for m in matches[:4]:
            a,b=max(0,m.start()-700),min(len(source),m.end()+1200)
            print(json.dumps({"term":term,"offset":m.start(),
                              "context":source[a:b]},ensure_ascii=False),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
