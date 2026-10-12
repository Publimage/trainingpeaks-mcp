"""Read-only comparison of native sacrificial Training Plan date-move canary backup."""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
from scripts.ironman_jobs.chasing_lab_date_move_canary import BACKUP, read, day, OWNER, PLAN

async def main():
    if not BACKUP.exists():
        print(json.dumps({"stage":"NO_BACKUP","plan":PLAN}))
        return 1
    b=json.loads(BACKUP.read_text())
    original=b["workout"]
    async with TPClient() as c:
        u=await c._get_user_data()
        if u.get("personId")!=OWNER:
            return 2
        current,note=await read(c)
    keys=sorted(set(original)|set(current))
    changed=[{"field":k,"original":str(original.get(k))[:80],"live":str(current.get(k))[:80]} for k in keys if original.get(k)!=current.get(k)]
    print(json.dumps({"stage":"LAB_MOVE_AUDIT","plan":PLAN,"date":day(current),"id":current.get("workoutId"),"notes_preserved":note==b["note_sha256"],"changed":changed},ensure_ascii=False))
    return 0
if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
