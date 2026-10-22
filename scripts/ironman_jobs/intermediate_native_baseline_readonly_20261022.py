"""Read-only native Builder and StructuredStrength baseline for Intermediate 24W plan 684602.
No provider writes, no athlete calendar access, no mutations of repository state.
"""
from __future__ import annotations

import asyncio
import collections
import json
from datetime import date
import httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access, _headers, STRENGTH_API_BASE

PLAN=684602
PERSON=6678583
OWNER=2116886
TITLE="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
START=date(2026,10,5)
WINDOWS=[("2026-10-05","2026-11-29"),("2026-11-30","2027-01-24"),("2027-01-25","2027-03-21")]
FOCUS={3996858792,3996859347,3996860483,3996863151,3996864785,3996868548,3996861535,3996872965,3996862048}

def require(check, label):
    if not check: raise RuntimeError(label)

def rel(day):
    dt=date.fromisoformat(str(day)[:10])
    index=(dt-START).days
    require(0<=index<168,"DATE_OUTSIDE_24W")
    return index//7+1,index%7+1

def short_step(seg):
    rows=[]
    for group in seg:
        for s in group.get("steps") or []:
            rows.append({"name":s.get("name"),"length":s.get("length"),"targets":s.get("targets"),
                         "intensity":s.get("intensityClass"),"repeat":group.get("length")})
    return rows

async def run():
    async with TPClient() as c:
        me=await c._get_user_data()
        require(me.get("personId")==OWNER,"OWNER_MISMATCH")
        r=await c.get(f"/plans/v1/plans/{PLAN}")
        require(not r.is_error and isinstance(r.data,dict),"PLAN_READ")
        p=r.data
        require(p.get("planId")==PLAN and p.get("planPersonId")==PERSON and
                p.get("ownerPersonId")==OWNER and p.get("title")==TITLE and
                p.get("isPublic") is True and p.get("workoutCount")==259 and
                p.get("weekCount")==24 and str(p.get("startDate"))[:10]==START.isoformat(),
                "PLAN_GUARD")
        classic=[]
        for a,b in WINDOWS:
            v=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{a}/{b}")
            require(not v.is_error and isinstance(v.data,list),f"CLASSIC_WINDOW_{a}")
            classic.extend(v.data)
        require(len(classic)==229 and len({x.get("workoutId") for x in classic})==229,
                f"CLASSIC_COUNT_{len(classic)}")
        bysport=collections.Counter()
        issues=[]
        for w in classic:
            wk,d=rel(w.get("workoutDay"))
            t=w.get("workoutTypeValueId")
            bysport[t]+=1
            st=w.get("structure")
            if not isinstance(st,dict) or not isinstance(st.get("structure"),list) or not st["structure"]:
                issues.append({"workoutId":w.get("workoutId"),"week":wk,"day":d,"problem":"MISSING_NATIVE_STRUCTURE"})
                continue
            if st.get("primaryLengthMetric")=="duration":
                end=st["structure"][-1].get("end")
                target=(w.get("totalTimePlanned") or 0)*3600
                if not isinstance(end,(int,float)) or abs(end-target)>2:
                    issues.append({"workoutId":w.get("workoutId"),"week":wk,"day":d,"problem":"DURATION_MISMATCH","end":end,"planned_sec":target})
            if t==1 and (not w.get("distancePlanned") or not w.get("totalTimePlanned")):
                issues.append({"workoutId":w.get("workoutId"),"problem":"SWIM_DISTANCE_OR_DURATION_MISSING"})
        require(dict(bysport)=={1:71,2:71,3:87},f"SPORT_COUNTS_{dict(bysport)}")
        focus={x.get("workoutId"):x for x in classic if x.get("workoutId") in FOCUS}
        require(len(focus)==len(FOCUS),f"FOCUS_COUNT_{len(focus)}")
        print(json.dumps({"stage":"INTERMEDIATE_NATIVE_CLASSIC_AUDIT","plan":PLAN,
             "count":len(classic),"sports":dict(bysport),"issue_count":len(issues),
             "issues":issues[:75]},ensure_ascii=False),flush=True)
        for wid,w in sorted(focus.items()):
            wk,d=rel(w.get("workoutDay"))
            st=w.get("structure") or {}
            print(json.dumps({"stage":"INTERMEDIATE_FOCUS_NATIVE","id":wid,"week":wk,"day":d,
              "title":w.get("title"),"duration_min":round((w.get("totalTimePlanned") or 0)*60,2),
              "distance_m":w.get("distancePlanned"),"primaryMetric":st.get("primaryIntensityMetric"),
              "lengthMetric":st.get("primaryLengthMetric"),"end":(st.get("structure") or [{}])[-1].get("end"),
              "polyline_points":len(st.get("polyline") or []),
              "steps":short_step(st.get("structure") or [])},ensure_ascii=False,default=str),flush=True)
        token_data=await _access(c)
        token=token_data[1]
        error=token_data[2]
        require(not error and token,"NATIVE_AUTH")
        async with httpx.AsyncClient(timeout=35,follow_redirects=False) as h:
            req=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/plans/{PLAN}/workouts/2026-10-05/2027-03-25",
                            headers=_headers(token))
            require(req.status_code==200,f"STRENGTH_RANGE_HTTP_{req.status_code}")
            payload=req.json()
            items=payload.get("data") if isinstance(payload,dict) else payload
            require(isinstance(items,list) and len(items)==30,f"STRENGTH_COUNT_{len(items) if isinstance(items,list) else 'INVALID'}")
            summary=[];minutes=0
            for x in items:
                wid=x.get("id") or x.get("workoutId")
                require(wid,"STRENGTH_ID_MISSING")
                detail=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/{wid}",headers=_headers(token))
                require(detail.status_code==200,f"STRENGTH_DETAIL_HTTP_{wid}_{detail.status_code}")
                data=detail.json()
                w=data.get("data") if isinstance(data,dict) else data
                require(isinstance(w,dict) and w.get("workoutType")=="StructuredStrength" and w.get("calendarId")==PERSON,
                        f"STRENGTH_DETAIL_SCOPE_{wid}")
                wk,d=rel(w.get("prescribedDate"))
                dur=w.get("prescribedDurationInSeconds")
                require(isinstance(dur,(int,float)) and dur>0,f"STRENGTH_DURATION_{wid}")
                minutes+=round(dur/60)
                bs=w.get("blocks") or []
                summary.append({"id":wid,"week":wk,"day":d,"title":w.get("title"),
                                "minutes":round(dur/60),"blocks":len(bs),
                                "exercises":sum(len(b.get("prescriptions") or []) for b in bs),
                                "sets":sum(len(z.get("sets") or []) for b in bs for z in b.get("prescriptions") or [])})
            require(minutes==750,f"STRENGTH_TOTAL_MIN_{minutes}")
            summary.sort(key=lambda v:(v["week"],v["day"]))
            print(json.dumps({"stage":"INTERMEDIATE_NATIVE_STRENGTH_AUDIT","plan":PLAN,
                "count":len(summary),"total_minutes":minutes,"workouts":summary},ensure_ascii=False),flush=True)
        print(json.dumps({"stage":"INTERMEDIATE_BASELINE_READONLY_PASS","plan":PLAN,
            "classic":229,"strength":30,"total":259,"mutations":0},ensure_ascii=False),flush=True)

if __name__=="__main__":
    try: asyncio.run(run())
    except Exception as e:
        print(json.dumps({"stage":"INTERMEDIATE_BASELINE_SAFE_STOP","reason":str(e)[:420]},ensure_ascii=False),flush=True)
        raise
