"""Compact READ-ONLY discovery of Training Plan folder routes from public TP JS.

GET-only public assets. No authentication, cookies, browser automation, or
provider writes. Emits only plan-folder route candidates and short snippets.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urljoin, urlparse
import httpx

BASE="https://app.trainingpeaks.com/"
TERMS=(
    "plansWithAccess",
    "planFolder",
    "trainingPlanFolder",
    "folderId",
    "folderName",
    "CreateFolder",
    "RenameFolder",
    "DeleteFolder",
    "MovePlan",
)
MAX_ASSETS=220
MAX_BYTES=13_000_000


def trusted(url:str)->bool:
    host=(urlparse(url).hostname or "").lower()
    return host=="trainingpeaks.com" or host.endswith(".trainingpeaks.com")


def snippets(source:str,term:str)->list[str]:
    out=[]
    for m in list(re.finditer(re.escape(term),source,re.I))[:3]:
        a,b=max(0,m.start()-650),min(len(source),m.end()+1100)
        out.append(re.sub(r"\s+"," ",source[a:b])[:1750])
    return out


def route_literals(source:str)->list[str]:
    # Capture likely TP path literals near plans/folders/commands without dumping bundle.
    vals=set()
    for m in re.finditer(r"""['"]([^'"]{1,220})['"]""",source):
        value=m.group(1)
        low=value.lower()
        if (
            ("/plans/" in low or "planswithaccess" in low)
            and any(x in low for x in ("folder","group","move","copy","plan"))
        ):
            vals.add(value)
    return sorted(vals)[:160]


async def main()->int:
    async with httpx.AsyncClient(timeout=24,follow_redirects=False,headers={"User-Agent":"Mozilla/5.0"}) as h:
        page=await h.get(BASE)
        if page.status_code!=200:
            print(json.dumps({"stage":"STOP_INDEX","http":page.status_code}),flush=True);return 2
        urls=re.findall(r"""<script[^>]+src=['"]([^'"]+)""",page.text,re.I)
        urls=[urljoin(BASE,u) for u in urls if ".js" in u]
        urls=list(dict.fromkeys(u for u in urls if trusted(u)))[:MAX_ASSETS]
        sem=asyncio.Semaphore(8)
        async def inspect(url):
            async with sem:
                try:r=await h.get(url)
                except Exception as e:return None
                if r.status_code!=200 or len(r.content)>MAX_BYTES:return None
                src=r.text
                hits={term:snippets(src,term) for term in TERMS if re.search(re.escape(term),src,re.I)}
                routes=route_literals(src)
                if not hits and not routes:return None
                return {"asset":urlparse(url).path,"hits":hits,"routes":routes}
        rows=[x for x in await asyncio.gather(*(inspect(u) for u in urls)) if x]
        print(json.dumps({"stage":"PLAN_FOLDER_FRONTEND_SUMMARY","assets_scanned":len(urls),"matched":len(rows),"provider_writes":0}),flush=True)
        for row in rows:
            # Prefer exact route candidates, then only short snippets for folder-specific terms.
            compact={
                "asset":row["asset"],
                "routes":row["routes"],
                "hits":{k:v for k,v in row["hits"].items() if k in {"plansWithAccess","planFolder","trainingPlanFolder","CreateFolder","RenameFolder","DeleteFolder","MovePlan"}},
            }
            print(json.dumps(compact,ensure_ascii=False)[:12000],flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
