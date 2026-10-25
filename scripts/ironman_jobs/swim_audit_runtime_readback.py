"""Read back the live private CSS bridge; no config or provider writes."""
import asyncio
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.ironman_jobs.swim_audit_runtime_activation import readback
if __name__ == "__main__":
    print(json.dumps(asyncio.run(readback()), sort_keys=True))
