"""READ ONLY: locate exact Workout Library API proxy definitions in current public TrainingPeaks JS."""
from __future__ import annotations
import asyncio,json,re,httpx
URL="https://app.trainingpeaks.com/release-20261016-83ae3fe/modules-6ddaaa87.js"
METHODS=(
 "getAllWorkoutLibraries","getAllActivitiesForLibrary","getActivityFromLibrary",
 "deleteActivityFromLibrary","updateActivityInLibrary","createActivityInLibrary",
 "renameLibrary","deleteLibrary","createLibrary"
)
async def main()->int:
    async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
        r=await h.get(URL)
    if r.status_code!=200 or len(r.content)>14000000:return 2
    src=r.text;rows=[]
    for method in METHODS:
        for pat in (f'key:"{method}"',f"{method}:function",f'"{method}":function'):
            for m in list(re.finditer(re.escape(pat),src))[:8]:
                a,b=max(0,m.start()-1600),min(len(src),m.end()+5600)
                rows.append({"method":method,"pattern":pat,"offset":m.start(),
                             "context":src[a:b].replace("\n"," ").replace("\r"," ")[:7200]})
    print(json.dumps({"stage":"SUMMARY","definitions":len(rows),"writes":0}),flush=True)
    for row in rows[:24]:
        print(json.dumps({"stage":"DEF",**row,"writes":0},ensure_ascii=False),flush=True)
    print(json.dumps({"stage":"COMPLETE","provider_writes":0}),flush=True)
    return 0
if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
