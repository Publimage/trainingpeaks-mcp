"""READ ONLY: exact apiProxy.copyTrainingPlan call site from current public TP frontend."""
from __future__ import annotations
import asyncio,json,re,httpx
URL="https://app.trainingpeaks.com/release-20261016-83ae3fe/modules-8af7f7d8.js"
async def main():
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
    r=await h.get(URL)
  if r.status_code!=200:return 2
  src=r.text
  hits=list(re.finditer(re.escape("apiProxy.copyTrainingPlan"),src))
  print(json.dumps({"stage":"SUMMARY","hits":len(hits),"writes":0}),flush=True)
  for m in hits[:8]:
    a,b=max(0,m.start()-9000),min(len(src),m.end()+9000)
    print(json.dumps({"stage":"COPY_CALL","offset":m.start(),
      "context":src[a:b].replace("\n"," ").replace("\r"," ")[:18000],
      "writes":0},ensure_ascii=False),flush=True)
  print(json.dumps({"stage":"COMPLETE","provider_writes":0}),flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
