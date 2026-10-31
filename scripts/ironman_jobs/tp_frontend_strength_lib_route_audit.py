"""Read-only discovery of TrainingPeaks frontend library Strength API routes.

Public HTML/JS GET only, bounded sizes; no auth tokens, provider writes, or
calendar operations. Captures only route-adjacent text, not raw bundles.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urljoin, urlparse
import httpx

PAGES=("https://app.trainingpeaks.com/","https://home.trainingpeaks.com/","https://app.trainingpeaks.com/coach/")
PATTERNS=("exerciselibrary","StructuredStrength","/rx/activity/","strengthworkout","libraryitem","WorkoutLibrary","System.import","release-2026","webpack","javascript:")
ALLOWED=("trainingpeaks.com","peakswaresb.com")
MAX_BYTES=5000000
MAX_SCRIPTS=90

def trusted(url:str)->bool:
    host=(urlparse(url).hostname or "").lower()
    return any(host==v or host.endswith("."+v) for v in ALLOWED)

def snippets(content:str)->list[str]:
    found=[]
    for p in PATTERNS:
        for m in list(re.finditer(re.escape(p),content,re.IGNORECASE))[:10]:
            a,b=max(0,m.start()-95),min(len(content),m.end()+155)
            raw=content[a:b].replace("\\n"," ").replace("\\r"," ")
            raw=re.sub(r"(?:Bearer\\s+[A-Za-z0-9._-]+|Authorization\\s*[:=]\\s*[^,;]+)","<redacted>",raw,flags=re.I)
            found.append(raw[:260])
    return found[:55]


async def main()->int:
    base="https://app.trainingpeaks.com/"
    targets=("onCopyCalendarActivityToLibrary","copyCalendarActivityToLibrary",
             "onCopyActivityToLibrary","copyWorkoutToLibrary",
             "addWorkoutToLibrary","addWorkoutToLibraryFolder")
    async with httpx.AsyncClient(timeout=22,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
        page=await h.get(base)
        if page.status_code!=200:return 3
        urls=re.findall(r"""<script[^>]+src=['"]([^'"]+)""",page.text,re.I)
        urls=[urljoin(base,u) for u in urls if "release-" in u and ".js" in u]
        urls=list(dict.fromkeys(x for x in urls if trusted(x)))[:180]
        print(json.dumps({"phase":"INDEX","asset_count":len(urls)}),flush=True)
        sem=asyncio.Semaphore(8)
        async def inspect(url):
            async with sem:
                try:
                    resp=await h.get(url)
                    if resp.status_code!=200:
                        return {"asset":urlparse(url).path,"http":resp.status_code}
                    if len(resp.content)>13000000:
                        return {"asset":urlparse(url).path,"status":"OVERSIZED","bytes":len(resp.content)}
                    body=resp.text
                    hits=[]
                    for term in targets:
                        mm=list(re.finditer(re.escape(term),body,re.I))
                        if mm:
                            matches=[]
                            for m in mm[:3]:
                                a,b=max(0,m.start()-180),min(len(body),m.end()+260)
                                matches.append(body[a:b].replace("\n"," "))
                            hits.append({"term":term,"count":len(mm),"samples":matches})
                    return {"asset":urlparse(url).path,"bytes":len(body),"hits":hits}
                except Exception as e:
                    return {"asset":urlparse(url).path,"error":type(e).__name__}
        results=await asyncio.gather(*(inspect(url) for url in urls))
        matched=[r for r in results if r.get("hits")]
        print(json.dumps({"phase":"SUMMARY","scanned":len(results),"matched":len(matched),
                          "skipped_oversize":[x for x in results if x.get("status")=="OVERSIZED"],
                          "failed":[x for x in results if x.get("http")!=None or x.get("error")][:12]},
                          ensure_ascii=False),flush=True)
        for r in matched:
            print(json.dumps(r,ensure_ascii=False),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
