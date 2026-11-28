"""READ-ONLY public TrainingPeaks frontend route discovery for organization APIs.

Scans only public app.trainingpeaks.com HTML/JS assets with GET requests.
No login, bearer token, cookies, provider mutations, or browser automation.
Prints bounded route-adjacent snippets for Training Plan folders and Workout
Library organization operations.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urljoin, urlparse

import httpx

BASE = "https://app.trainingpeaks.com/"
ALLOWED = ("trainingpeaks.com",)
MAX_ASSET_BYTES = 13_000_000
MAX_ASSETS = 220

TERMS = (
    "plansWithAccess",
    "trainingPlanFolder",
    "planFolder",
    "folderId",
    "folderName",
    "createTrainingPlanFolder",
    "deleteTrainingPlanFolder",
    "renameTrainingPlanFolder",
    "moveTrainingPlan",
    "copyTrainingPlan",
    "/plans/v1/",
    "exerciseLibraryId",
    "deleteActivityFromLibrary",
    "getAllWorkoutLibraries",
    "/exerciselibrary/v1/libraries/",
)


def trusted(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == item or host.endswith("." + item) for item in ALLOWED)


def contexts(source: str, term: str, *, limit: int = 4) -> list[str]:
    rows = []
    for match in list(re.finditer(re.escape(term), source, re.I))[:limit]:
        start = max(0, match.start() - 1200)
        end = min(len(source), match.end() + 2200)
        snippet = source[start:end].replace("\n", " ").replace("\r", " ")
        snippet = re.sub(r"(?i)(authorization|bearer|cookie|password|secret|token)\s*[:=]\s*\S+", "<redacted>", snippet)
        rows.append(snippet[:3400])
    return rows


async def main() -> int:
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=24, follow_redirects=False, headers=headers) as client:
        page = await client.get(BASE)
        if page.status_code != 200:
            print(json.dumps({"stage": "STOP_INDEX", "http": page.status_code}), flush=True)
            return 2

        urls = re.findall(r"""<script[^>]+src=['"]([^'"]+)""", page.text, re.I)
        urls = [urljoin(BASE, value) for value in urls if ".js" in value]
        urls = list(dict.fromkeys(url for url in urls if trusted(url)))[:MAX_ASSETS]
        print(json.dumps({"stage": "INDEX", "asset_count": len(urls)}), flush=True)

        sem = asyncio.Semaphore(8)

        async def inspect(url: str) -> dict:
            async with sem:
                try:
                    response = await client.get(url)
                except Exception as exc:
                    return {"asset": urlparse(url).path, "error": type(exc).__name__}
                if response.status_code != 200:
                    return {"asset": urlparse(url).path, "http": response.status_code}
                if len(response.content) > MAX_ASSET_BYTES:
                    return {"asset": urlparse(url).path, "status": "OVERSIZED", "bytes": len(response.content)}
                source = response.text
                hits = []
                for term in TERMS:
                    found = list(re.finditer(re.escape(term), source, re.I))
                    if found:
                        hits.append({
                            "term": term,
                            "count": len(found),
                            "contexts": contexts(source, term),
                        })
                return {"asset": urlparse(url).path, "bytes": len(response.content), "hits": hits}

        rows = await asyncio.gather(*(inspect(url) for url in urls))
        matched = [row for row in rows if row.get("hits")]
        print(json.dumps({
            "stage": "SUMMARY",
            "scanned": len(rows),
            "matched_assets": len(matched),
            "provider_writes": 0,
        }), flush=True)
        for row in matched:
            print(json.dumps(row, ensure_ascii=False)[:14000], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
