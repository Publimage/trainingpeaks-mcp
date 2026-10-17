"""READ-ONLY locate the frontend module containing /plans/v1/plansWithAccess.

Then enumerate nearby plan/folder path literals from that same bounded module.
Public JS GET only; no auth or provider writes.
"""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx

BASE="https://app.trainingpeaks.com/"
NEEDLE="/plans/v1/plansWithAccess"
MAX_ASSETS=260
MAX_BYTES=13_000_000

def trusted(url):
 h=(urlparse(url).hostname or "").lower()
 return h=="trainingpeaks.com" or h.endswith(".trainingpeaks.com")

async def main():
 async with httpx.AsyncClient(timeout=28,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
  p=await h.get(BASE)
  if p.status_code!=200:return 2
  urls=re.findall(r"""<script[^>]+src=['"]([^'"]+)""",p.text,re.I)
  urls=list(dict.fromkeys(urljoin(BASE,u) for u in urls if ".js" in u and trusted(urljoin(BASE,u))))[:MAX_ASSETS]
  sem=asyncio.Semaphore(8)
  async def one(url):
   async with sem:
    try:r=await h.get(url)
    except Exception:return None
    if r.status_code!=200 or len(r.content)>MAX_BYTES:return None
    pos=r.text.find(NEEDLE)
    if pos<0:return None
    # Wide bounded window around the known API literal.
    a,b=max(0,pos-18000),min(len(r.text),pos+42000)
    body=r.text[a:b]
    literals=[]
    for m in re.finditer(r"""(?P<q>['"])(?P<v>(?:\\.|(?!\1).){1,320})(?P=q)""",body):
     v=m.group("v"); low=v.lower()
     if any(k in low for k in ("/plans","folder","planfolder","trainingplan","planswithaccess","move","remove","copy")):
      literals.append(v)
    contexts=[]
    for term in (NEEDLE,"folder","move","remove","copy"):
     for m in list(re.finditer(re.escape(term),body,re.I))[:8]:
      x,y=max(0,m.start()-900),min(len(body),m.end()+1800)
      contexts.append({"term":term,"context":re.sub(r"\s+"," ",body[x:y])[:2700]})
    return {"asset":urlparse(url).path,"position":pos,"literals":sorted(set(literals))[:240],"contexts":contexts[:30]}
  rows=[x for x in await asyncio.gather(*(one(u) for u in urls)) if x]
  print(json.dumps({"stage":"PLANS_WITH_ACCESS_MODULE_LOCATE","assets":len(urls),"matched":len(rows),"provider_writes":0}),flush=True)
  for row in rows:print(json.dumps(row,ensure_ascii=False)[:26000],flush=True)
 return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
