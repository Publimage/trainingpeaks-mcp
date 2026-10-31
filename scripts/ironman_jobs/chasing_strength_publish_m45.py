"""Guarded Chasing M45 native library publisher. No athlete dates."""
import asyncio,json,sys,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.ironman_jobs.chasing_strength_native_publish_common import publish
if __name__=="__main__":
    try:
        raise SystemExit(asyncio.run(publish("M45")))
    except Exception as e:
        tb=traceback.extract_tb(e.__traceback__)
        print(json.dumps({"stage":"UNHANDLED_EXCEPTION","type":type(e).__name__,
                          "message":str(e)[:110],"line":tb[-1].lineno if tb else None}),flush=True)
        raise SystemExit(1)
