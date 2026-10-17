"""Structural Chasing Week 1 run-date redistribution only. Library unchanged."""
import asyncio,json
from chasing_w01_w04_intermediate_layout_common import run
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(run(1)))
 except Exception as e:
  print(json.dumps({"stage":"W01_STOP","reason":str(e)[:240],"no_blind_retry":True}),flush=True)
  raise
