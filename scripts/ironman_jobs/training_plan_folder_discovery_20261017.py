"""READ ONLY discovery of TrainingPeaks Training Plan folder/group metadata.
No writes. Prints raw keys and probes plausible GET-only endpoints.
"""
import asyncio, json
from tp_mcp.client import TPClient

async def main():
    async with TPClient() as c:
        me = await c._get_user_data()
        plans = await c.get("/plans/v1/plans")
        if plans.is_error:
            raise RuntimeError(plans.message)
        rows = plans.data or []
        samples = [p for p in rows if int(p.get("planId") or 0) in {684762,684463,684555,684543,684484,684206,679801,684602,685173}]
        print(json.dumps({
            "stage":"PLAN_FOLDER_DISCOVERY_READONLY",
            "owner": me.get("personId") if isinstance(me,dict) else None,
            "plan_count": len(rows),
            "sample_keys": sorted({k for p in samples for k in p.keys()}),
            "samples": [{k:p.get(k) for k in p.keys() if any(x in k.lower() for x in ("folder","group","category","parent","archive","planid","title"))} for p in samples],
        }, ensure_ascii=False), flush=True)
        for path in [
            "/plans/v1/folders",
            "/plans/v1/planfolders",
            "/plans/v1/trainingplanfolders",
            "/plans/v1/groups",
        ]:
            r = await c.get(path)
            print(json.dumps({
                "probe":path,
                "is_error":r.is_error,
                "error_code":r.error_code.value if r.error_code else None,
                "message":r.message,
                "data":r.data if not r.is_error else None,
            }, ensure_ascii=False)[:12000], flush=True)
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
