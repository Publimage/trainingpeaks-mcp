"""Private plan native Strength recovery notes, W9-W16, no duration changes."""
import asyncio,json
from chasing_strength_rests_plan_common import run
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(run(9,16)))
 except Exception as e:
  print(json.dumps({"stage":"STOP","weeks":[9,16],"reason":str(e)[:240],"no_blind_retry":True}),flush=True)
  raise
