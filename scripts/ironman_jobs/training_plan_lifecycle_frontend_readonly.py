"""READ ONLY: exact current public frontend definition for whole-plan removal."""
from __future__ import annotations
import asyncio,json,re
from urllib.parse import urljoin,urlparse
import httpx
BASE="https://app.trainingpeaks.com/"
PATTERNS=('key:"removeTrainingPlan"','key:"deleteTrainingPlan"','removeTrainingPlan:function','deleteTrainingPlan:function')
async def main()->int:
  async with httpx.AsyncClient(timeout=22,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
    page=await h.get(BASE)
    if page.status_code!=200:return 2
    urls=re.findall(r"""<script[^>]+src=['"]([^'"]+)""",page.text,re.I)
    urls=list(dict.fromkeys(urljoin(BASE,u) for u in urls if ".js" in u and "release-" in u))[:180]
    sem=asyncio.Semaphore(8)
    async def inspect(url):
      async with sem:
        try:
          r=await h.get(url)
          if r.status_code!=200 or len(r.content)>14000000:return []
          src=r.text;rows=[]
          for pat in PATTERNS:
            for m in re.finditer(re.escape(pat),src):
              a,b=max(0,m.start()-2200),min(len(src),m.end()+5200)
              rows.append({"asset":urlparse(url).path,"pattern":pat,"offset":m.start(),
                           "context":src[a:b].replace("\n"," ").replace("\r"," ")[:7500]})
          return rows
        except Exception:return []
    chunks=await asyncio.gather(*(inspect(u) for u in urls))
    rows=[x for ch in chunks for x in ch]
    print(json.dumps({"stage":"SUMMARY","definitions":len(rows),"writes":0}),flush=True)
    for row in rows[:12]:
      print(json.dumps({"stage":"REMOVE_DEF",**row,"writes":0},ensure_ascii=False),flush=True)
    print(json.dumps({"stage":"COMPLETE","provider_writes":0}),flush=True)
    return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
