"""READ ONLY audit of the sacrificial date-move canary backup and live provider."""
import asyncio,json,hashlib
from pathlib import Path
OWNER=2116886
PLAN=684484
ID=3995256662
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_move_lab_canary_684484.json"

def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()

async def main():
    print(json.dumps({"stage":"AUDIT_BEGIN","backup_exists":BACKUP.exists()}),flush=True)
    if not BACKUP.exists():return 1
    b=json.loads(BACKUP.read_text())
    original=b["workout"]
    from tp_mcp.client import TPClient
    async with TPClient() as c:
        me=await c._get_user_data()
        if me.get("personId")!=OWNER:return 2
        p=await c.get(f"/plans/v1/plans/{PLAN}")
        if p.is_error or p.data.get("isPublic") is not False:return 3
        r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/2027-07-05/2027-07-15")
        if r.is_error or not isinstance(r.data,list) or len(r.data)!=1:return 4
        current=r.data[0]
        n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-07-05/2027-07-15")
        if n.is_error:return 5
    keys=sorted(set(original)|set(current))
    changes=[{"field":k,"old":str(original.get(k))[:100],"new":str(current.get(k))[:100]} for k in keys if original.get(k)!=current.get(k)]
    print(json.dumps({"stage":"AUDIT_RESULT","plan":PLAN,"id":current.get("workoutId"),"day":current.get("workoutDay"),"notes_match":digest(n.data)==b["note_sha256"],"changed":changes},ensure_ascii=False),flush=True)
    return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
