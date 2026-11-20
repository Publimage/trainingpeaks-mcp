"""One-shot bounded CHASING native notes 12..21."""
import asyncio
from chasing_native_notes_core_20261015 import run_batch

if __name__ == "__main__":
    asyncio.run(run_batch(11,21))
