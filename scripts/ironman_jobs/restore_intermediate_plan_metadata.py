"""Restore private Intermediate plan author/contact metadata after provider title PUT.

Uses same owner's untouched sibling Intermediate test plan as source. No
guessing hardcoded email/name. Does not touch workout, notes or publication.
"""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
TARGET=684602
SOURCE=684463
TARGET_TITLE="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
SOURCE_TITLE="[MCP TEST] IRONMAN Intermediate 24W - Archive Pilot"
FIRST="2026-10-05"
LAST="2027-04-01"
class Stop(Exception):pass
def must(v,s):
 if not v:raise Stop(s)
async def run():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  async def get(i):
   r=await c.get(f"/plans/v1/plans/{i}")
   must(not r.is_error and isinstance(r.data,dict),"PLAN_READ_FAILED")
   return r.data
  async def notes():
   r=await c.get(f"/plans/v1/plans/{TARGET}/calendarNote/{FIRST}/{LAST}")
   must(not r.is_error and isinstance(r.data,list),"NOTES_READ_FAILED")
   return json.dumps(r.data,sort_keys=True)
  s=await get(SOURCE); p=await get(TARGET)
  must((s.get("planId"),s.get("title"),s.get("workoutCount"))
       ==(SOURCE,SOURCE_TITLE,13),"REFERENCE_CHANGED")
  must(s.get("isPublic") is False and s.get("price") in (None,0),"REFERENCE_NOT_PRIVATE")
  must(isinstance(s.get("author"),str) and s["author"].strip()
       and isinstance(s.get("planEmail"),str) and "@" in s["planEmail"],
       "REFERENCE_METADATA_MISSING")
  must((p.get("planId"),p.get("title"),p.get("workoutCount"),p.get("weekCount"))
       ==(TARGET,TARGET_TITLE,259,24),"TARGET_CHANGED")
  must(p.get("author") is None and p.get("planEmail") is None,"TARGET_ALREADY_HAS_METADATA")
  must(p.get("isPublic") is False and p.get("price") in (None,0),"TARGET_NOT_PRIVATE")
  backup=await notes()
  core=("planId","workoutCount","weekCount","startDate","endDate","isPublic","price","dayCount")
  # Source metadata is known-good for the same coach's private Intermediate pilot.
  r=await c._request("PUT",f"/plans/v1/plans/{TARGET}",json={
      "planId":TARGET,"title":TARGET_TITLE,"author":s["author"],
      "planEmail":s["planEmail"]},_retry_on_401=False)
  if r.is_error:
   print("METADATA_RESTORE_RESULT_AMBIGUOUS",str(r.error_code));return 2
  new=await get(TARGET)
  must(new.get("title")==TARGET_TITLE,"TITLE_DRIFT")
  must(new.get("author")==s["author"] and new.get("planEmail")==s["planEmail"],
       "METADATA_NOT_RESTORED")
  must({k:new.get(k) for k in core}=={k:p.get(k) for k in core},"PLAN_CORE_CHANGED")
  must(await notes()==backup,"NOTES_CHANGED")
  print("RENAME_AND_METADATA_VERIFIED",json.dumps({
    "planId":TARGET,"name":TARGET_TITLE,"weekCount":24,"workoutCount":259,
    "notesCount":35,"authorRestored":True,"planEmailRestored":True,
    "metadataSourcePrivateIntermediatePilot":SOURCE},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(run()))
 except Stop as e:print("STOP_REVIEW",str(e),flush=True);raise SystemExit(2)
