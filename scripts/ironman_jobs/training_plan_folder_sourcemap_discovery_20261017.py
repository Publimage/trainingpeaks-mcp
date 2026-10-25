"""READ-ONLY source-map discovery for Training Plan folder API code.

Fetches one public TrainingPeaks JS bundle and its public source map when
available, then prints only source files/snippets containing plan-folder
symbols. No auth and no provider writes.
"""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx

ASSET="https://app.trainingpeaks.com/release-20261016-83ae3fe/modules-46171c53.js"
TERMS=("getTrainingPlanFolders","createTrainingPlanFolder","renameTrainingPlanFolder",
       "deleteTrainingPlanFolder","movePlanToFolder","removePlanFromFolder",
       "assignPlanFolder","plansWithAccess","planFolderId","planFolderName")


def trusted(url:str)->bool:
 h=(urlparse(url).hostname or "").lower()
 return h=="trainingpeaks.com" or h.endswith(".trainingpeaks.com")


def around(text:str,term:str)->list[str]:
 out=[]
 for m in list(re.finditer(re.escape(term),text,re.I))[:8]:
  a,b=max(0,m.start()-1300),min(len(text),m.end()+2600)
  out.append(re.sub(r"\s+"," ",text[a:b])[:3900])
 return out


async def main()->int:
 async with httpx.AsyncClient(timeout=30,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
  asset=await h.get(ASSET)
  if asset.status_code!=200:return 2
  tail=asset.text[-4000:]
  mm=re.search(r"sourceMappingURL=([^\s*]+)",tail)
  print(json.dumps({"stage":"ASSET","bytes":len(asset.content),"source_map_declared":bool(mm),"provider_writes":0}),flush=True)
  if not mm:
   return 0
  map_url=urljoin(ASSET,mm.group(1).strip())
  if not trusted(map_url):return 3
  sm=await h.get(map_url)
  print(json.dumps({"stage":"MAP","http":sm.status_code,"bytes":len(sm.content) if sm.status_code==200 else 0}),flush=True)
  if sm.status_code!=200 or len(sm.content)>80_000_000:return 4
  data=sm.json()
  sources=data.get("sources") or []
  contents=data.get("sourcesContent") or []
  matches=[]
  for idx,content in enumerate(contents):
   if not isinstance(content,str):continue
   terms=[t for t in TERMS if re.search(re.escape(t),content,re.I)]
   if not terms:continue
   snippets={t:around(content,t) for t in terms}
   matches.append({"source":sources[idx] if idx<len(sources) else str(idx),"terms":terms,"snippets":snippets})
  print(json.dumps({"stage":"SOURCE_MATCH_SUMMARY","count":len(matches)}),flush=True)
  for row in matches[:18]:
   print(json.dumps(row,ensure_ascii=False)[:12000],flush=True)
 return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
