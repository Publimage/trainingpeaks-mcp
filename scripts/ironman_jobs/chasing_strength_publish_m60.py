"""Chasing M60 native DRAFT library-only publisher with guarded exception report."""
import asyncio,json,traceback,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.ironman_jobs.chasing_strength_native_publish_common import publish
if __name__=="__main__":
    try:
        raise SystemExit(asyncio.run(publish("M60")))
    except Exception as err:
        tb=traceback.extract_tb(err.__traceback__)
        print(json.dumps({"stage":"EXCEPTION_BEFORE_VERIFIED_WRITE","type":type(err).__name__,
                          "msg":str(err)[:150],
                          "line":tb[-1].lineno if tb else None,
                          "name":tb[-1].name if tb else None}),flush=True)
        raise SystemExit(1)
