"""Read-only independent postflight for CHASING athlete-guide v1.1 replacement."""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=685173
NOTE=2664007
FIRST="2027-01-04"
END="2027-06-20"
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Advanced | Italiano"
EXPECTED={
  97265:("CHASING THE SLOT 24W — Guida Atleta v1.1.pdf",145361),
  97222:("CHASING_THE_SLOT_24W_Guida_Settimana_per_Settimana_v1.0.pdf",222837),
  97223:("CHASING_THE_SLOT_24W_Guida_Fueling_Nutrizione_v1.0.pdf",121278),
}
def nid(n): return int(n.get("id") or n.get("calendarNoteId") or n.get("noteId"))
async def main():
 async with TPClient() as c:
  me=await c._get_user_data(); assert isinstance(me,dict) and me.get("personId")==OWNER
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  assert not p.is_error and isinstance(p.data,dict)
  assert (p.data.get("title"),p.data.get("weekCount"),p.data.get("workoutCount"),p.data.get("isPublic"),int(p.data.get("price") or 0))==(TITLE,24,276,True,199)
  r=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{FIRST}/{END}")
  assert not r.is_error and isinstance(r.data,list) and len(r.data)==31
  n=next(x for x in r.data if nid(x)==NOTE)
  assert n.get("title")=="START | Come usare Chasing the Slot" and len(n.get("description",""))>900
  rows={int(a["id"]):(str(a["fileName"]),int(a["contentLength"])) for a in n.get("attachments",[])}
  assert rows==EXPECTED
  print("CHASING_ATHLETE_GUIDE_V11_POSTFLIGHT_PASS",json.dumps({
    "planId":PLAN,"noteId":NOTE,"attachments":[{"id":i,"fileName":v[0],"bytes":v[1]} for i,v in sorted(rows.items())],
    "notes":31,"workouts":276,"public":True,"price":199,"provider_writes":0
  },ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__": raise SystemExit(asyncio.run(main()))
