"""Move one CHASING native strength W19 canary in-place, exact ID preserved."""
import asyncio,json
from chasing_strength_relayout_common_20261022 import run
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(run(True)))
 except Exception as e:
  print(json.dumps({"stage":"SAFE_STOP_NATIVE_STRENGTH_CANARY","reason":str(e)[:400],"no_blind_retry":True}),flush=True)
  raise
