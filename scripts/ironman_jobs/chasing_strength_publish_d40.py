"""Guarded native Chasing Strength D40 publication; library only, no dates."""
import asyncio
from scripts.ironman_jobs.chasing_strength_native_publish_common import publish
if __name__=="__main__":
    raise SystemExit(asyncio.run(publish("D40")))
