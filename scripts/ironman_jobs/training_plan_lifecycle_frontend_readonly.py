"""READ ONLY: locate current TrainingPeaks whole-plan copy/delete action definitions and call sites."""
from __future__ import annotations
import asyncio, json, re
from urllib.parse import urljoin, urlparse
import httpx

BASE = "https://app.trainingpeaks.com/"
TERMS = (
    "copyTrainingPlan",
    "deleteTrainingPlan",
    'key:"copyTrainingPlan"',
    'key:"deleteTrainingPlan"',
    "copyplan",
    "removeplan",
)

async def main():
    async with httpx.AsyncClient(
        timeout=22, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0"}
    ) as h:
        page = await h.get(BASE)
        if page.status_code != 200:
            return 2
        urls = re.findall(r"""<script[^>]+src=['"]([^'"]+)""", page.text, re.I)
        urls = list(dict.fromkeys(urljoin(BASE, u) for u in urls if ".js" in u and "release-" in u))[:180]
        sem = asyncio.Semaphore(8)

        async def inspect(url):
            async with sem:
                try:
                    r = await h.get(url)
                    if r.status_code != 200 or len(r.content) > 14000000:
                        return []
                    src = r.text
                    rows = []
                    seen = set()
                    for term in TERMS:
                        for m in list(re.finditer(re.escape(term), src, re.I))[:50]:
                            key = m.start() // 300
                            if key in seen:
                                continue
                            seen.add(key)
                            a, b = max(0, m.start() - 5000), min(len(src), m.end() + 8500)
                            ctx = src[a:b].replace("\n", " ").replace("\r", " ")
                            if any(x in ctx for x in ("_buildUrl", "apiProxy", "trainingPlanActions", "coachTrainingPlanLibraryActions", "._post(", "._delete(")):
                                rows.append({
                                    "asset": urlparse(url).path,
                                    "term": term,
                                    "offset": m.start(),
                                    "context": ctx[:13500],
                                })
                    return rows
                except Exception:
                    return []

        chunks = await asyncio.gather(*(inspect(u) for u in urls))
        rows = [x for ch in chunks for x in ch]
        rows.sort(key=lambda x: (
            0 if "_buildUrl" in x["context"] and ("._post(" in x["context"] or "._delete(" in x["context"]) else 1,
            0 if 'key:"copyTrainingPlan"' in x["context"] or 'key:"deleteTrainingPlan"' in x["context"] else 1,
            x["asset"], x["offset"],
        ))
        print(json.dumps({"stage": "SUMMARY", "hits": len(rows), "writes": 0}), flush=True)
        for row in rows[:20]:
            print(json.dumps({"stage": "LIFECYCLE", **row, "writes": 0}, ensure_ascii=False), flush=True)
        print(json.dumps({"stage": "COMPLETE", "provider_writes": 0}), flush=True)
        return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
