"""READ-ONLY compact inventory of plan-related URL/path literals in TP frontend JS."""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx

BASE="https://app.trainingpeaks.com/"
KNOWN="https://app.trainingpeaks.com/release-20261016-83ae3fe/modules-46171c53.js"
MAX_BYTES=13_000_000

def trusted(url):
 h=(urlparse(url).hostname or "").lower()
 return h=="trainingpeaks.com" or h.endswith(".trainingpeaks.com")

def literals(src):
 vals=set()
 pat=r"""(?P<q>['"])(?P<v>(?:\\.|(?!\1).){1,300})(?P=q)"""
 for m in re.finditer(pat,src):
  v=m.group("v"); low=v.lower()
  if ("plan" in low or "folder" in low) and (
    "/" in v or "api" in low or ("folder" in low and any(x in low for x in ("plan","move","rename","create","delete","remove","assign")))
  ):
   if len(v)<=300: vals.add(v)
 return vals

async def main():
 async with httpx.AsyncClient(timeout=28,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
  p=await h.get(BASE)
  if p.status_code!=200:return 2
  urls=re.findall(r"""<script[^>]+src=['"]([^'"]+)""",p.text,re.I)
  urls=[urljoin(BASE,u) for u in urls if ".js" in u]
  urls=list(dict.fromkeys([u for u in urls if trusted(u)]+[KNOWN]))
  sem=asyncio.Semaphore(8)
  async def one(url):
   async with sem:
    try:r=await h.get(url)
    except Exception:return []
    if r.status_code!=200 or len(r.content)>MAX_BYTES:return []
    return sorted(literals(r.text))
  allv=set()
  for rows in await asyncio.gather(*(one(u) for u in urls)): allv.update(rows)
  route=[v for v in allv if "/" in v]
  other=[v for v in allv if "/" not in v]
  route.sort(key=lambda x:(0 if "/plans" in x.lower() else 1,len(x),x.lower()))
  other.sort(key=lambda x:(0 if "plan" in x.lower() else 1,len(x),x.lower()))
  print(json.dumps({
    "stage":"TP_PLAN_PATH_LITERALS",
    "asset_count":len(urls),
    "route_count":len(route),
    "routes":route[:180],
    "other_apiish":other[:80],
    "provider_writes":0
  },ensure_ascii=False),flush=True)
 return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
