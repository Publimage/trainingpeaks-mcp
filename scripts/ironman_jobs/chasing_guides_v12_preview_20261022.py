"""Read-only source/live TrainingPeaks reconciliation + PDF generation QA."""
import asyncio,json
from chasing_guides_release_common_20261022 import run
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(run(False)))
 except Exception as e:
  print(json.dumps({"stage":"STOP_CHASING_GUIDES_V12_PREVIEW","reason":str(e)[:450],"provider_writes":0}),flush=True)
  raise
