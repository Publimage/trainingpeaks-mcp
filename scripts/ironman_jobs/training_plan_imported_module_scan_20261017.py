"""READ-ONLY scan of imported webpack modules used by TP Training Plan Library.

Public JS GET only. Finds definitions of module IDs imported immediately after
the CoachTrainingPlanLibrary translations and emits only bounded module bodies
that contain plan/folder/API vocabulary.
"""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx

BASE="https://app.trainingpeaks.com/"
MODULE_IDS=(46047,70573,85114,13585,29754,53701,44155,7073,89975,93411,24645,79387,46607,57483,96463,15340)
MAX_ASSETS=240
MAX_BYTES=13_000_000

def trusted(url):
 h=(urlparse(url).hostname or "").lower()
 return h=="trainingpeaks.com" or h.endswith(".trainingpeaks.com")

def body_for(src,mid):
 # webpack module shape: 46047:(e,t,n)=>{...}, next id boundary
 patterns=(rf"(?:^|,)\s*{mid}:\s*\([^)]*\)\s*=>\s*\{{",
           rf"(?:^|,)\s*{mid}:\s*function\([^)]*\)\s*\{{")
 for pat in patterns:
  m=re.search(pat,src)
  if not m:continue
  start=m.start()
  # Bounded chunk; enough to recover endpoint constants/calls without dumping bundle.
  return src[start:min(len(src),start+22000)]
 return None

async def main():
 async with httpx.AsyncClient(timeout=28,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
  page=await h.get(BASE)
  if page.status_code!=200:return 2
  urls=re.findall(r"""<script[^>]+src=['"]([^'"]+)""",page.text,re.I)
  urls=list(dict.fromkeys(urljoin(BASE,u) for u in urls if ".js" in u and trusted(urljoin(BASE,u))))[:MAX_ASSETS]
  sem=asyncio.Semaphore(8)
  async def scan(url):
   async with sem:
    try:r=await h.get(url)
    except Exception:return []
    if r.status_code!=200 or len(r.content)>MAX_BYTES:return []
    src=r.text; out=[]
    for mid in MODULE_IDS:
     body=body_for(src,mid)
     if not body:continue
     low=body.lower()
     strings=sorted(set(
       m.group("v") for m in re.finditer(r"""(?P<q>['"])(?P<v>(?:\\.|(?!\1).){1,260})(?P=q)""",body)
       if any(k in m.group("v").lower() for k in ("plan","folder","/plans","training"))
     ))
     contexts=[]
     for term in ("folder","/plans","trainingPlan","plansWithAccess","move","remove","rename","create"):
      mm=re.search(re.escape(term),body,re.I)
      if mm:
       a,b=max(0,mm.start()-500),min(len(body),mm.end()+1500)
       contexts.append(re.sub(r"\s+"," ",body[a:b])[:2000])
     out.append({"module":mid,"asset":urlparse(url).path,"strings":strings[:100],"contexts":contexts[:6]})
    return out
  rows=[]
  for part in await asyncio.gather(*(scan(u) for u in urls)): rows.extend(part)
  relevant=[x for x in rows if x["strings"] or x["contexts"]]
  print(json.dumps({"stage":"PLAN_LIBRARY_MODULE_SCAN","assets":len(urls),"module_defs":len(rows),"relevant":len(relevant),"provider_writes":0}),flush=True)
  for row in relevant[:40]:
   print(json.dumps(row,ensure_ascii=False)[:14000],flush=True)
 return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
