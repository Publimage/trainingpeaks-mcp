"""Private CHASING controlled redistribution W21-W23."""
import asyncio,json
from chasing_monday_distribution_common import run
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(run(21,23)))
 except Exception as e:
  print(json.dumps({"stage":"STOP_W21_W23","reason":str(e)[:300],"no_blind_retry":True}),flush=True)
  raise
