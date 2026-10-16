"""Read-only full-plan preview of 41 Beginner FTP->RPE Builder edits."""
import asyncio,json
from tp_mcp.client import TPClient
from scripts.ironman_jobs.beginner_rpe_native_common_20261016 import preflight
async def main():
 async with TPClient() as c:
  before,notes,compiled,anchor=await preflight(c)
  details=[compiled[i][1] for i in sorted(compiled)]
  print(json.dumps({"stage":"BEGINNER_RPE_41_PREFLIGHT_PASS","count":len(details),
    "cadence_count":sum(x["cadence_fields"] for x in details),
    "weeks":sorted(set(x["week"] for x in details)),
    "plan_original_count":len(before),"issues":[],
    "preview":details,"provider_writes":0},ensure_ascii=False),flush=True)
if __name__=="__main__":asyncio.run(main())
