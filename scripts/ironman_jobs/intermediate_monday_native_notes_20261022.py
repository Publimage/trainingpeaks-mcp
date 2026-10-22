"""Intermediate 24W: guarded correction of six obsolete Monday-off native notes.
Plan scoped native CalendarNotes only. Canary first, then five remaining notes.
This job does not modify workouts, Strength, attachments, athletes, or libraries.
"""
import asyncio
import hashlib
import json
import sys
from tp_mcp.client import TPClient

PLAN=684602
OWNER=2116886
PERSON=6678583
TITLE="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
NOTES={1:2654984,2:2652651,3:2652952,5:2652955,6:2652956,7:2652983}
OLD="Il lunedì resta libero da allenamento strutturato. Le sedute saltate non vanno compresse nei giorni successivi."
NEW="Il lunedì prevede soltanto il richiamo breve di forza, con fatica contenuta per non compromettere il lavoro di qualità del martedì. Le sedute saltate non vanno compresse nei giorni successivi."

def need(ok,msg):
    if not ok:raise RuntimeError(msg)

def row_sig(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()

async def run(canary:bool):
    target_weeks=[1] if canary else [2,3,5,6,7]
    async with TPClient() as c:
        user=await c._get_user_data()
        need(isinstance(user,dict) and user.get("personId")==OWNER,"OWNER_MISMATCH")
        pr=await c.get(f"/plans/v1/plans/{PLAN}")
        need(not pr.is_error and isinstance(pr.data,dict),"PLAN_READ_FAILED")
        p=pr.data
        need((p.get("planId"),p.get("planPersonId"),p.get("ownerPersonId"),p.get("title"),p.get("weekCount"),p.get("workoutCount"),p.get("isPublic"))==
             (PLAN,PERSON,OWNER,TITLE,24,259,True),"PUBLIC_PLAN_SCOPE_MISMATCH")
        need(p.get("price")==179,"PLAN_PRICE_MISMATCH")
        async def get_notes():
            r=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2026-10-05/2027-04-01")
            need(not r.is_error and isinstance(r.data,list) and len(r.data)==35,"NOTE_SET_MISMATCH")
            need(len({int(x.get("id") or 0) for x in r.data})==35,"DUPLICATE_NATIVE_NOTES")
            return {int(x["id"]):x for x in r.data}
        before=await get_notes()
        baseline={k:row_sig(v) for k,v in before.items()}
        need(all(nid in before for nid in NOTES.values()),"TARGET_NOTES_MISSING")
        snapshots={}
        for w,nid in NOTES.items():
            n=before[nid]
            need(n.get("planId")==PLAN and "SETTIMANA "+str(w) in (n.get("title") or ""),"TARGET_NOTE_WRONG_WEEK")
            expected_date=f"2026-{10+(w+3)//5:02d}-01" if False else None
            need(n.get("noteDate") and str(n["noteDate"])[:4] in ("2026","2027"),"TARGET_NOTE_DATE_MISSING")
            desc=n.get("description") or ""
            need(desc.count(OLD)==1 or (desc.count(NEW)==1 and OLD not in desc),"TARGET_DESCRIPTION_DRIFT")
            snapshots[nid]={"date":n["noteDate"],"title":n["title"],"attachments":n.get("attachments") or [],
                            "old":desc}
        changed=[]
        for w in target_weeks:
            nid=NOTES[w]
            n=before[nid]
            if NEW in n["description"] and OLD not in n["description"]:
                print(json.dumps({"stage":"INTERMEDIATE_NOTE_ALREADY_VERIFIED","week":w,"id":nid}),flush=True)
                continue
            current=await get_notes()
            need(row_sig(current[nid])==row_sig(n),"TARGET_CHANGED_DURING_WRITE")
            payload=dict(n)
            payload["description"]=n["description"].replace(OLD,NEW)
            payload["planId"]=PLAN
            r=await c._request("PUT",f"/plans/v1/plans/{PLAN}/calendarNote/{nid}",json=payload,_retry_on_401=False)
            # Always reconcile provider state, including any uncertain HTTP response.
            after=await get_notes()
            item=after[nid]
            success=(item.get("description")==payload["description"] and
                     item.get("title")==n.get("title") and
                     item.get("noteDate")==n.get("noteDate") and
                     item.get("attachments")==n.get("attachments") and
                     item.get("planId")==PLAN)
            need(success,"NOTE_WRITE_NOT_VERIFIED_STOP_"+str(nid)+"_"+str(getattr(r,"error_code",None)))
            for other_id,other_sig in baseline.items():
                if other_id not in changed and other_id!=nid:
                    need(row_sig(after[other_id])==other_sig,"UNRELATED_NOTE_CHANGED_"+str(other_id))
            changed.append(nid)
            print(json.dumps({"stage":"INTERMEDIATE_NOTE_WRITE_VERIFIED","week":w,"id":nid}),flush=True)
        final=await get_notes()
        for w,nid in NOTES.items():
            actual=final[nid]
            expected=NEW if w in target_weeks or before[nid].get("description","").count(NEW) else OLD
            need(actual.get("description","").count(expected)==1 and actual.get("title")==snapshots[nid]["title"]
                 and actual.get("noteDate")==snapshots[nid]["date"] and actual.get("attachments")==snapshots[nid]["attachments"],
                 "POSTFLIGHT_TARGET_"+str(nid))
        again=await c.get(f"/plans/v1/plans/{PLAN}")
        need(not again.is_error and again.data.get("workoutCount")==259 and again.data.get("isPublic") is True
             and again.data.get("price")==179,"POSTFLIGHT_PLAN_METADATA")
        print(json.dumps({"stage":"INTERMEDIATE_MON_NOTES_VERIFIED","mode":"canary" if canary else "remaining",
                          "changed":changed,"native_notes":35,"workouts":259,"price":179,
                          "athlete_writes":0,"library_writes":0},ensure_ascii=False),flush=True)

if __name__=="__main__":
    mode=sys.argv[1] if len(sys.argv)>1 else ""
    need(mode in ("canary","remaining"),"MODE_REQUIRED")
    asyncio.run(run(mode=="canary"))
