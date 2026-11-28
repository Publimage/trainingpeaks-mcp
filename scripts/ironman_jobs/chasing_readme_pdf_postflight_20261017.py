"""Read-only postflight for CHASING START-note guide attachments."""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=685173
NOTE=2664007
FIRST="2027-01-04"
END="2027-06-20"
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
EXPECTED={
  97221:("CHASING_THE_SLOT_24W_Guida_Atleta_v1.0.pdf",138919),
  97222:("CHASING_THE_SLOT_24W_Guida_Settimana_per_Settimana_v1.0.pdf",222837),
  97223:("CHASING_THE_SLOT_24W_Guida_Fueling_Nutrizione_v1.0.pdf",121278),
}
class Stop(Exception):pass
def must(v,m):
    if not v: raise Stop(m)
def nid(n): return int(n.get("id") or n.get("calendarNoteId") or n.get("noteId"))
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(isinstance(me,dict) and me.get("personId")==OWNER,"OWNER_WRONG")
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  must(not p.is_error and isinstance(p.data,dict),"PLAN_READ_FAILED")
  must((p.data.get("title"),p.data.get("weekCount"),p.data.get("workoutCount"),p.data.get("isPublic"))==
       (TITLE,24,276,False),"PLAN_DRIFT")
  r=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{FIRST}/{END}")
  must(not r.is_error and isinstance(r.data,list) and len(r.data)==31,"NOTES_DRIFT")
  n=next((x for x in r.data if nid(x)==NOTE),None)
  must(n is not None and n.get("title")=="START | Come usare Chasing the Slot","START_NOTE_DRIFT")
  must(len(n.get("description",""))>900,"START_BODY_DRIFT")
  rows={int(a["id"]):(str(a["fileName"]),int(a["contentLength"])) for a in n.get("attachments",[])}
  must(rows==EXPECTED,"ATTACHMENTS_DRIFT")
  print("CHASING_README_PDF_POSTFLIGHT_PASS",json.dumps({
    "planId":PLAN,"noteId":NOTE,"attachment_count":3,
    "attachments":[{"id":i,"fileName":v[0],"bytes":v[1]} for i,v in sorted(rows.items())],
    "workouts":276,"notes":31,"provider_writes":0
  },ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":
 try: raise SystemExit(asyncio.run(main()))
 except Stop as e:
  print("STOP_REVIEW",str(e),flush=True); raise SystemExit(2)
