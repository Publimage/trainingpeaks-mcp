"""Guarded replace only two outdated guide PDFs, preserving fueling and all plan data."""
import asyncio,json
from chasing_guides_release_common_20261022 import run
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(run(True)))
 except Exception as e:
  print(json.dumps({"stage":"STOP_CHASING_GUIDES_V12_RELEASE","reason":str(e)[:450],"no_blind_retry":True}),flush=True)
  raise
