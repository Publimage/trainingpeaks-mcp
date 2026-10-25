"""READ-ONLY exact symbol occurrence scan in current TrainingPeaks plan chunk."""
from __future__ import annotations
import asyncio,json,re
import httpx

URL="https://app.trainingpeaks.com/release-20261016-83ae3fe/modules-46171c53.js"
TERMS=(
 "getTrainingPlanFolders","createTrainingPlanFolder","renameTrainingPlanFolder",
 "deleteTrainingPlanFolder","movePlanToFolder","removePlanFromFolder","assignPlanFolder"
)

def kind(ctx:str)->str:
 low=ctx.lower()
 if "unabletogettrainingplanfolders" in low or "unabletocreatetrainingplanfolder" in low:
  return "I18N_NEIGHBORHOOD"
 if any(x in low for x in (".get(", ".post(", ".put(", ".delete(", "fetch(", "axios", "api.")):
  return "API_ADJACENT"
 return "CODE_OR_UNKNOWN"

async def main():
 async with httpx.AsyncClient(timeout=30,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
  r=await h.get(URL)
 if r.status_code!=200:return 2
 src=r.text
 out=[]
 for term in TERMS:
  for m in re.finditer(re.escape(term),src,re.I):
   a,b=max(0,m.start()-3000),min(len(src),m.end()+5000)
   ctx=re.sub(r"\s+"," ",src[a:b])
   out.append({"term":term,"pos":m.start(),"kind":kind(ctx),"context":ctx[:8000]})
 print(json.dumps({"stage":"EXACT_PLAN_FOLDER_SYMBOLS","bytes":len(r.content),"occurrences":len(out),"provider_writes":0}),flush=True)
 # Non-i18n first and capped to avoid operator truncation.
 out.sort(key=lambda x:(0 if x["kind"]!="I18N_NEIGHBORHOOD" else 1,x["term"],x["pos"]))
 for row in out[:16]:print(json.dumps(row,ensure_ascii=False)[:10000],flush=True)
 return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
