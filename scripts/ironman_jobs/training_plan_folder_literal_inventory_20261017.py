"""READ-ONLY literal inventory for Training Plan folder API discovery.

Downloads one public TrainingPeaks JS bundle and emits distinct short string
literals/template fragments containing plan/folder-related API vocabulary.
No authentication or provider writes.
"""
from __future__ import annotations
import asyncio,json,re
import httpx

URL="https://app.trainingpeaks.com/release-20261016-83ae3fe/modules-46171c53.js"

async def main()->int:
 async with httpx.AsyncClient(timeout=30,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
  r=await h.get(URL)
 if r.status_code!=200:return 2
 src=r.text
 vals=set()
 # ordinary quoted strings
 for m in re.finditer(r"""(?P<q>['"])(?P<v>(?:\\.|(?!\1).){1,240})(?P=q)""",src):
  v=m.group("v")
  low=v.lower()
  if any(k in low for k in ("planfolder","plan-folder","trainingplanfolder","training-plan-folder","planswithaccess","moveplan","removeplan","assignplan","/plans/","folder")):
   if not any(x in low for x in ("translation","unableto","newtrainingplanfolder","folderselectcontainer","workoutlibraryfolder")):
    vals.add(v)
 # template literals / nearby URL fragments
 for term in ("plansWithAccess","planFolder","trainingPlanFolder","movePlanToFolder","removePlanFromFolder"):
  for m in list(re.finditer(re.escape(term),src,re.I))[:12]:
   a,b=max(0,m.start()-260),min(len(src),m.end()+420)
   frag=re.sub(r"\s+"," ",src[a:b])
   vals.add("CTX:"+frag)
 rows=sorted(vals,key=lambda x:(0 if "/" in x else 1,len(x),x.lower()))
 print(json.dumps({"stage":"PLAN_FOLDER_LITERAL_INVENTORY","count":len(rows),"provider_writes":0}),flush=True)
 for v in rows[:220]: print(json.dumps(v,ensure_ascii=False),flush=True)
 return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
