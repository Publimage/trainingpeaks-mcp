"""GET-only scan for Training Plan folder function names in public TP JS."""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx

BASE="https://app.trainingpeaks.com/"
TERMS=(
 "getTrainingPlanFolders","createTrainingPlanFolder","renameTrainingPlanFolder",
 "deleteTrainingPlanFolder","movePlanToFolder","removePlanFromFolder",
 "assignPlanFolder","trainingPlanFolderId","trainingPlanFolderName",
 "getPlanFolders","planFolderId","planFolderName"
)
MAX_ASSETS=220
MAX_BYTES=13_000_000

def trusted(url):
 h=(urlparse(url).hostname or "").lower()
 return h=="trainingpeaks.com" or h.endswith(".trainingpeaks.com")

async def main():
 async with httpx.AsyncClient(timeout=24,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as c:
  page=await c.get(BASE)
  if page.status_code!=200:return 2
  urls=re.findall(r"""<script[^>]+src=['"]([^'"]+)""",page.text,re.I)
  urls=list(dict.fromkeys(urljoin(BASE,u) for u in urls if ".js" in u and trusted(urljoin(BASE,u))))[:MAX_ASSETS]
  sem=asyncio.Semaphore(8)
  async def one(url):
   async with sem:
    try:r=await c.get(url)
    except Exception:return []
    if r.status_code!=200 or len(r.content)>MAX_BYTES:return []
    src=r.text; out=[]
    for term in TERMS:
     ms=list(re.finditer(re.escape(term),src,re.I))
     for m in ms[:5]:
      a,b=max(0,m.start()-1800),min(len(src),m.end()+3000)
      ctx=re.sub(r"\s+"," ",src[a:b])
      # discard obvious locale dictionary neighborhoods when possible
      out.append({"term":term,"asset":urlparse(url).path,"pos":m.start(),"context":ctx[:4800]})
    return out
  hits=[]
  for rows in await asyncio.gather(*(one(u) for u in urls)):hits.extend(rows)
  print(json.dumps({"stage":"PLAN_FOLDER_SYMBOL_SCAN","assets":len(urls),"hit_count":len(hits),"provider_writes":0}),flush=True)
  # Prefer smaller assets and contexts that contain URL-ish/API verbs.
  hits.sort(key=lambda x:(0 if re.search(r"/plans/|axios|fetch\(|\.get\(|\.post\(|\.put\(|\.delete\(",x["context"],re.I) else 1,len(x["context"]),x["asset"]))
  for h in hits[:24]:
   print(json.dumps(h,ensure_ascii=False)[:6000],flush=True)
 return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
