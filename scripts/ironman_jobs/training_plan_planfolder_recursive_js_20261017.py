"""Public GET-only recursive TrainingPeaks JS chunk discovery for planfolder routes.

Starts from app.trainingpeaks.com, follows only same-release JavaScript asset
references found in HTML/JS, and reports bounded contexts containing planfolder
API vocabulary. No authentication, cookies, browser automation or provider writes.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import deque
from urllib.parse import urljoin, urlparse

import httpx

BASE = "https://app.trainingpeaks.com/"
MAX_ASSETS = 700
MAX_BYTES = 14_000_000
TERMS = (
    "/planfolder/",
    "planfolder/v1",
    "folder/all",
    "getTrainingPlanFolders",
    "createTrainingPlanFolder",
    "renameTrainingPlanFolder",
    "deleteTrainingPlanFolder",
    "movePlanToFolder",
    "removePlanFromFolder",
)


def trusted(url: str, release_prefix: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "app.trainingpeaks.com"
        and parsed.path.startswith(release_prefix)
        and parsed.path.endswith(".js")
    )


def js_refs(text: str, base_url: str, release_prefix: str) -> list[str]:
    candidates = set()
    # Absolute/relative JS-looking strings embedded in runtime/chunk maps.
    for m in re.finditer(r"""(?P<q>['"])(?P<v>[^'"]{1,240}\.js(?:\?[^'"]*)?)(?P=q)""", text):
        value = m.group("v")
        url = urljoin(base_url, value)
        if trusted(url, release_prefix):
            candidates.add(url)
    # Bare hashed module/chunk filenames are common in webpack runtime maps.
    for m in re.finditer(r"""(?:modules|runtime|main|vendor|chunk|[A-Za-z0-9_-]+)-[A-Fa-f0-9]{6,}\.js""", text):
        url = urljoin(base_url, m.group(0))
        if trusted(url, release_prefix):
            candidates.add(url)
    return sorted(candidates)


def contexts(source: str) -> list[dict]:
    rows = []
    for term in TERMS:
        for m in list(re.finditer(re.escape(term), source, re.I))[:8]:
            a, b = max(0, m.start() - 1800), min(len(source), m.end() + 3800)
            ctx = re.sub(r"\s+", " ", source[a:b])
            rows.append({"term": term, "pos": m.start(), "context": ctx[:5600]})
    return rows


async def main() -> int:
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=28, follow_redirects=False, headers=headers) as client:
        page = await client.get(BASE)
        if page.status_code != 200:
            print(json.dumps({"stage": "STOP_INDEX", "http": page.status_code}))
            return 2

        rel = re.search(r"""(/release-[^/'"]+/)""", page.text)
        if not rel:
            print(json.dumps({"stage": "STOP_RELEASE_NOT_FOUND"}))
            return 3
        release_prefix = rel.group(1)

        initial = []
        for src in re.findall(r"""<script[^>]+src=['"]([^'"]+)""", page.text, re.I):
            url = urljoin(BASE, src)
            if trusted(url, release_prefix):
                initial.append(url)

        queue = deque(dict.fromkeys(initial))
        seen: set[str] = set()
        matched = []
        failed = []

        while queue and len(seen) < MAX_ASSETS:
            batch = []
            while queue and len(batch) < 12 and len(seen) + len(batch) < MAX_ASSETS:
                url = queue.popleft()
                if url not in seen:
                    batch.append(url)
                    seen.add(url)

            async def fetch(url: str):
                try:
                    r = await client.get(url)
                except Exception as exc:
                    return url, None, type(exc).__name__
                if r.status_code != 200:
                    return url, None, f"HTTP_{r.status_code}"
                if len(r.content) > MAX_BYTES:
                    return url, None, "OVERSIZED"
                return url, r.text, None

            fetched = await asyncio.gather(*(fetch(url) for url in batch))
            for url, source, err in fetched:
                if err:
                    failed.append({"asset": urlparse(url).path, "error": err})
                    continue
                assert source is not None
                hits = contexts(source)
                if hits:
                    matched.append({
                        "asset": urlparse(url).path,
                        "bytes": len(source.encode("utf-8")),
                        "hits": hits,
                    })
                for ref in js_refs(source, url, release_prefix):
                    if ref not in seen:
                        queue.append(ref)

        print(json.dumps({
            "stage": "PLANFOLDER_RECURSIVE_PUBLIC_JS",
            "release_prefix": release_prefix,
            "assets_scanned": len(seen),
            "queued_remaining": len(queue),
            "matched_assets": len(matched),
            "failed_count": len(failed),
            "provider_writes": 0,
        }), flush=True)
        for row in matched[:30]:
            print(json.dumps(row, ensure_ascii=False)[:22000], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
