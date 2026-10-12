"""Private CHASING controlled redistribution 5-8."""
import asyncio,json
from chasing_monday_distribution_common import run
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(run(5,8)))
 except Exception as e:
  print(json.dumps({"stage":"STOP_W5_W8","reason":str(e)[:300],"no_blind_retry":True}),flush=True)
  raise
