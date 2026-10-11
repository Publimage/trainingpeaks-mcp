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
PATTERNS=("exerciselibrary","StructuredStrength","/rx/activity/","strengthworkout","libraryitem","WorkoutLibrary")
ALLOWED=("trainingpeaks.com","peakswaresb.com")
MAX_BYTES=5000000
MAX_SCRIPTS=30

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
    async with httpx.AsyncClient(timeout=18,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
        scripts=[]
        for url in PAGES:
            try:
                r=await h.get(url)
                data=r.text[:MAX_BYTES] if "text/html" in r.headers.get("content-type","") else ""
                srcs=re.findall(r'<script[^>]+src="([^"]+)"',data,re.I)
                srcs=[urljoin(url,v) for v in srcs]
                scripts.extend([x for x in srcs if trusted(x)])
                print(json.dumps({"source":url,"http":r.status_code,"redirect":r.headers.get("location","")[:140],
                                  "html_bytes":len(data),"script_count":len(srcs),
                                  "script_sample":[urlparse(x).path for x in srcs[:15]],
                                  "matches":snippets(data)[:12]},ensure_ascii=False),flush=True)
            except (httpx.RequestError,ValueError) as e:
                print(json.dumps({"source":url,"error":type(e).__name__}),flush=True)
        unique=list(dict.fromkeys(scripts))[:MAX_SCRIPTS]
        print(json.dumps({"js_count":len(unique)}),flush=True)
        for src in unique:
            try:
                async with h.stream("GET",src) as r:
                    if r.status_code!=200:
                        print(json.dumps({"asset":urlparse(src).path[:160],"http":r.status_code}),flush=True)
                        continue
                    chunks=[];n=0
                    async for c in r.aiter_bytes():
                        n+=len(c)
                        if n>MAX_BYTES:break
                        chunks.append(c)
                    if n>MAX_BYTES:
                        print(json.dumps({"asset":urlparse(src).path[:160],"status":"OVERSIZE","bytes":n}),flush=True)
                        continue
                    js=b"".join(chunks).decode("utf-8","replace")
                hits=snippets(js)
                print(json.dumps({"asset":urlparse(src).path[:160],"status":"OK","bytes":len(js),"matches":hits},ensure_ascii=False),flush=True)
            except (httpx.RequestError,ValueError,UnicodeError) as e:
                print(json.dumps({"asset":urlparse(src).path[:160],"error":type(e).__name__}),flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
