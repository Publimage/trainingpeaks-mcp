"""Guarded Chasing in-place running calendar redistribution W05-W08."""
import asyncio,json
from scripts.ironman_jobs.chasing_monday_distribution_common import run
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(run(5,8)))
 except Exception as e:
  print(json.dumps({"stage":"STOP_W05_W08","reason":str(e)[:280],"no_blind_retry":True}),flush=True)
  raise
