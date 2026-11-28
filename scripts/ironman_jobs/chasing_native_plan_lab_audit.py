"""Run the same Strength Builder creation preflight without provider writes."""

import asyncio
import json

from tp_mcp.tools.strength import tp_create_strength_plan_lab_probe


async def main() -> int:
    result = await tp_create_strength_plan_lab_probe(dry_run=True)
    print(json.dumps(result), flush=True)
    return 0 if result.get("success") is True else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
