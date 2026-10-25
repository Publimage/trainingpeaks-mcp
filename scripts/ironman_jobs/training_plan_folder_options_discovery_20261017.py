"""Authenticated, non-mutating OPTIONS discovery for TrainingPeaks plan-folder routes.

Uses the same bearer/session as TPClient but issues OPTIONS only. It never sends
POST/PUT/PATCH/DELETE and never prints auth headers or response bodies.
"""
from __future__ import annotations

import asyncio
import json

from tp_mcp.client import TPClient

OWNER = 2116886

CANDIDATES = (
    "/planfolder/v1/folder",
    "/planfolder/v1/folder/all",
    "/planfolder/v1/folder/0",
    "/planfolder/v1/folder/plan",
    "/planfolder/v1/folder/0/plan",
    "/planfolder/v1/folder/0/plans",
    "/planfolder/v1/plan",
    "/planfolder/v1/plan/0",
    "/planfolder/v1/folder/move",
    "/planfolder/v1/folder/rename",
    "/planfolder/v1/folder/remove",
    "/planfolder/v1/folder/copy",
)


async def main() -> int:
    async with TPClient() as client:
        me = await client._get_user_data()
        if not isinstance(me, dict) or me.get("personId") != OWNER:
            print(json.dumps({"stage": "STOP_OWNER", "provider_writes": 0}))
            return 2

        token = await client._ensure_access_token()
        if not token.success:
            print(json.dumps({"stage": "STOP_AUTH", "provider_writes": 0}))
            return 3
        await client._ensure_client()
        assert client._client is not None

        rows = []
        for endpoint in CANDIDATES:
            await client._throttle()
            response = await client._client.request(
                "OPTIONS",
                client.base_url + endpoint,
                headers=client._get_headers(),
            )
            rows.append({
                "endpoint": endpoint,
                "http": response.status_code,
                "allow": response.headers.get("Allow"),
                "access_control_allow_methods": response.headers.get(
                    "Access-Control-Allow-Methods"
                ),
                "access_control_allow_origin": response.headers.get(
                    "Access-Control-Allow-Origin"
                ),
                "content_type": response.headers.get("Content-Type"),
                "content_length": response.headers.get("Content-Length"),
            })

        print(json.dumps({
            "stage": "PLAN_FOLDER_OPTIONS_DISCOVERY",
            "rows": rows,
            "provider_writes": 0,
        }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
