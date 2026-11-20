"""Set planned duration on all 30 native StructuredStrength workouts
in private Intermediate plan 684602. Duration comes from the canonical
minute labels already embedded in each approved workout title.
"""
from __future__ import annotations
import asyncio, copy, json, re
from datetime import date, timedelta
import httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE

PLAN=684602
PERSON=6678583
OWNER=2116886
TITLE="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
START="2026-10-05"
EXPECTED_COUNT=259
EXPECTED_NATIVE=30
EXPECTED_MINUTES=750

def must(v,msg):
    if not v: raise RuntimeError(msg)

def key(w):
    return ((w.get("title") or "").strip(), str(w.get("prescribedDate") or "")[:10])

def semantic(w):
    out={"id":str(w.get("id") or ""),"workoutType":w.get("workoutType"),
         "calendarId":w.get("calendarId"),"title":w.get("title"),
         "prescribedDate":str(w.get("prescribedDate") or "")[:10],
         "instructions":w.get("instructions"),
         "snapshot":{"totalBlocks":(w.get("snapshot") or {}).get("totalBlocks"),
                     "totalSets":(w.get("snapshot") or {}).get("totalSets")},
         "blocks":[]}
    for b in w.get("blocks") or []:
        bo={"blockType":b.get("blockType"),"title":b.get("title"),
            "coachNotes":b.get("coachNotes"),"prescriptions":[]}
        for p in b.get("prescriptions") or []:
            po={"exercise":{"id":str((p.get("exercise") or {}).get("id") or ""),
                            "title":(p.get("exercise") or {}).get("title")},
                "coachNotes":p.get("coachNotes"),
                "parameters":sorted([(x.get("parameter"),x.get("inputFormat")) for x in (p.get("parameters") or [])]),
                "sets":[]}
            for s in p.get("sets") or []:
                po["sets"].append(sorted([(v.get("parameter"),str(v.get("prescribedValue")),v.get("inputFormat"))
                                          for v in (s.get("parameterValues") or [])]))
            bo["prescriptions"].append(po)
        out["blocks"].append(bo)
    return out

async def native_range(h,token):
    end=(date.fromisoformat(START)+timedelta(weeks=24,days=2)).isoformat()
    r=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/plans/{PLAN}/workouts/{START}/{end}",headers=_headers(token))
    must(r.status_code==200,f"NATIVE_RANGE_HTTP_{r.status_code}")
    d=r.json(); d=d.get("data") if isinstance(d,dict) else d
    must(isinstance(d,list),"NATIVE_RANGE_SHAPE")
    return d

async def detail(h,token,wid):
    r=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/{wid}",headers=_headers(token))
    must(r.status_code==200,f"DETAIL_HTTP_{wid}_{r.status_code}")
    d=r.json().get("data") or {}
    must(d and d.get("workoutType")=="StructuredStrength",f"DETAIL_TYPE_{wid}")
    return d

async def main():
    async with TPClient() as c:
        me=await c._get_user_data(); p=await c.get(f"/plans/v1/plans/{PLAN}")
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        must(not p.is_error and isinstance(p.data,dict),"PLAN_READ")
        m=p.data
        must(m.get("planId")==PLAN and m.get("planPersonId")==PERSON and
             m.get("ownerPersonId")==OWNER and m.get("title")==TITLE and
             m.get("isPublic") is False and m.get("weekCount")==24 and
             m.get("workoutCount")==EXPECTED_COUNT and
             str(m.get("startDate") or "")[:10]==START,"PLAN_GUARD")
        _,token,err=await _access(c); must(not err and token,"STRENGTH_AUTH")
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as h:
            items=await native_range(h,token)
            must(len(items)==EXPECTED_NATIVE,"NATIVE_COUNT")
            expected={}
            for x in items:
                title,dt=key(x)
                mt=re.search(r"(\d+)(?:-(\d+))?'",title)
                must(mt,f"TITLE_DURATION_MISSING_{title}")
                expected[(title,dt)]=int(mt.group(2) or mt.group(1))
            must(len(expected)==EXPECTED_NATIVE,"NATIVE_DUPLICATE_KEY")
            must(sum(expected.values())==EXPECTED_MINUTES,f"EXPECTED_MINUTES_DRIFT_{sum(expected.values())}")
            changed=already=0
            for item in sorted(items,key=lambda x:(str(x.get("prescribedDate")),str(x.get("title")))):
                k=key(item); target=expected[k]*60
                wid=str(item.get("id") or item.get("workoutId") or ""); must(wid,"NATIVE_ID")
                before=await detail(h,token,wid)
                must(before.get("calendarId")==PERSON and key(before)==k,f"NATIVE_IDENTITY_{wid}")
                cur=before.get("prescribedDurationInSeconds")
                if cur==target:
                    already+=1; continue
                must(cur in (None,0),f"UNEXPECTED_EXISTING_DURATION_{wid}_{cur}")
                payload=copy.deepcopy(before); payload["prescribedDurationInSeconds"]=target
                try:
                    r=await h.post(STRENGTH_API_BASE+f"/rx/activity/v1/plans/{PLAN}/workouts/save",
                                   headers=_headers(token),json=payload)
                except httpx.RequestError:
                    after=await detail(h,token,wid)
                    must(after.get("prescribedDurationInSeconds")==target and semantic(after)==semantic(before),
                         f"AMBIGUOUS_DURATION_POST_{wid}")
                    changed+=1; continue
                must(r.status_code==200,f"DURATION_POST_REJECTED_{wid}_{r.status_code}")
                after=await detail(h,token,wid)
                must(after.get("prescribedDurationInSeconds")==target,f"DURATION_READBACK_{wid}")
                must(semantic(after)==semantic(before),f"NON_DURATION_DRIFT_{wid}")
                p2=await c.get(f"/plans/v1/plans/{PLAN}")
                must(not p2.is_error and p2.data.get("workoutCount")==EXPECTED_COUNT,f"PLAN_COUNT_DRIFT_{wid}")
                changed+=1
            final=await native_range(h,token); must(len(final)==EXPECTED_NATIVE,"FINAL_COUNT")
            total=0
            for x in final:
                wid=str(x.get("id") or x.get("workoutId") or "")
                d=await detail(h,token,wid); exp=expected[key(d)]*60
                must(d.get("prescribedDurationInSeconds")==exp,f"FINAL_DURATION_{wid}")
                total+=exp//60
            must(total==EXPECTED_MINUTES,"FINAL_MINUTES")
            pf=await c.get(f"/plans/v1/plans/{PLAN}")
            must(not pf.is_error and pf.data.get("workoutCount")==EXPECTED_COUNT and pf.data.get("isPublic") is False,"FINAL_PLAN_GUARD")
            print(json.dumps({"stage":"INTERMEDIATE_NATIVE_STRENGTH_DURATION_PASS","plan":PLAN,
                "native_strength":EXPECTED_NATIVE,"duration_minutes_total":total,
                "duration_hours_total":round(total/60,1),"changed":changed,
                "already_correct":already,"plan_count":EXPECTED_COUNT,
                "private_state_preserved":True,"non_duration_fields_verified":True,
                "athlete_calendar_writes":0},ensure_ascii=False),flush=True)
            return 0

if __name__=="__main__":
    try: raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(json.dumps({"stage":"SAFE_STOP","reason":str(exc)[:500]},ensure_ascii=False),flush=True)
        raise
