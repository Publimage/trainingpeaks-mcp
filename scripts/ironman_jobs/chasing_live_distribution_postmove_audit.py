"""Read-only 24W post-correction QA: native plan workouts, strength and weekly day-slot map.
Old baseline ledger is overlaid with approved granular moves, NOT the rejected redistribution candidate.
"""
import asyncio,json,httpx
from pathlib import Path
from datetime import date,timedelta
from collections import Counter,defaultdict
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
OWNER=2116886
PERSON=6682479
PLAN=685173
ANCHOR=date(2027,1,4)
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
LEDGER=Path("data/chasing_24w_day_ledger_20261012.json")
SUNDAY_SHIFT=frozenset({3,7,9,11})
DAY_CODE={"SW":"Swim","BI":"Bike","RU":"Run","ST":"Strength"}

def date_for(week,day):
    return (ANCHOR+timedelta(weeks=week-1,days=day)).isoformat()

def must(value,reason):
    if not value: raise RuntimeError(reason)

def canonical_expected():
    ledger=json.loads(LEDGER.read_text())
    must(len(ledger["weeks"])==24,"LEDGER_NOT_24W")
    count=Counter()
    for w in ledger["weeks"]:
        for idx,d in enumerate(w["days"]):
            for s in ("SW","BI","RU","ST"):
                if d.get(s,0)>0:
                    count[(date_for(w["week"],idx),s)]+=1
    must(sum(count.values())==276,"BASE_LEDGER_NOT_276")
    for week in range(1,24):
        key_src=(date_for(week,4),"RU")
        key_dst=(date_for(week,0),"RU")
        must(count[key_src]==1 and count[key_dst]==0,f"FRIDAY_SHIFT_INELIGIBLE_W{week}")
        count[key_src]-=1;count[key_dst]+=1
    for week in SUNDAY_SHIFT:
        src=(date_for(week,3),"RU")
        dest=(date_for(week,6),"RU")
        must(count[src]==1 and count[dest]==0,f"SUNDAY_SHIFT_INELIGIBLE_W{week}")
        count[src]-=1;count[dest]+=1
    return +count

async def run():
    expected=canonical_expected()
    observed=Counter()
    reports=defaultdict(list)
    titled=[]
    notes_count=0
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        p=await c.get(f"/plans/v1/plans/{PLAN}")
        must(not p.is_error and isinstance(p.data,dict),"PLAN_GET_FAILED")
        plan=p.data
        must(plan.get("planId")==PLAN and plan.get("planPersonId")==PERSON and
             plan.get("title")==TITLE and plan.get("isPublic") is False and
             plan.get("price") in (None,0) and plan.get("workoutCount")==276 and
             str(plan.get("startDate") or "")[:10]==ANCHOR.isoformat(),"PLAN_NOT_EXPECTED_PRIVATE_24W")
        for startweek in range(1,25,4):
            endweek=min(startweek+3,24)
            a=date_for(startweek,0)
            b=date_for(endweek,6)
            r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{a}/{b}")
            must(not r.is_error and isinstance(r.data,list),f"CLASSIC_GET_W{startweek}")
            n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{a}/{b}")
            must(not n.is_error and isinstance(n.data,list),f"NOTE_GET_W{startweek}")
            notes_count+=len(n.data)
            for w in r.data:
                dt=str(w.get("workoutDay") or "")[:10]
                kind={1:"SW",2:"BI",3:"RU"}.get(w.get("workoutTypeValueId"))
                must(kind is not None,"NON_ENDURANCE_CARD")
                observed[(dt,kind)]+=1
                if "test" in str(w.get("title") or "").lower() or "benchmark" in str(w.get("title") or "").lower():
                    titled.append({"day":dt,"kind":kind,"title":str(w.get("title") or "")[:90]})
                reports[dt].append(kind)
        _,token,err=await _access(c)
        must(not err and token is not None,"NO_NATIVE_STRENGTH_TOKEN")
        native=[]
        async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
            for week in range(1,25):
                a=date_for(week,0)
                b=date_for(week,6)
                r=await h.get(STRENGTH_API_BASE+
                       f"/rx/activity/v1/workouts/calendar/{PERSON}/{a}/{b}",headers=_headers(token))
                must(r.status_code==200 and isinstance(r.json(),list),f"STRENGTH_GET_W{week}")
                for w in r.json():
                    dt=str(w.get("prescribedDate") or "")[:10]
                    observed[(dt,"ST")]+=1
                    native.append({"day":dt,"id":w.get("id")})
                    reports[dt].append("ST")
    missing=[{"date":d,"sport":s,"n":v} for (d,s),v in (expected-observed).items()]
    extra=[{"date":d,"sport":s,"n":v} for (d,s),v in (observed-expected).items()]
    mon=[w for w in range(1,24) if reports[date_for(w,0)]]
    sun_active=[w for w in range(1,25) if reports[date_for(w,6)]]
    sat_bike=[w for w in range(1,24) if "BI" in reports[date_for(w,5)]]
    weekly=[]
    for w in range(1,25):
        n=sum(v for (d,s),v in observed.items() if date_for(w,0)<=d<=date_for(w,6))
        weekly.append(n)
    output={"stage":"CHASING_POSTMOVE_24W_QA","plan":PLAN,"private":True,
            "date_anchor":ANCHOR.isoformat(),"expected":sum(expected.values()),
            "observed":sum(observed.values()),"endurance":sum(v for (d,s),v in observed.items() if s!="ST"),
            "strength_native":len(native),"calendar_notes":notes_count,
            "missing":missing,"extra":extra,
            "duplicate_date_sport":[{"date":d,"sport":s,"n":n} for (d,s),n in observed.items() if n>1],
            "monday_active_weeks":mon,"sunday_active_weeks":sun_active,
            "sunday_off_weeks":[w for w in range(1,24) if w not in sun_active],
            "saturday_bike_weeks":sat_bike,"weekly_counts":weekly,
            "test_and_benchmark_titles":titled,
            "saturday_long_ride_preserved":len(sat_bike)==23,
            "no_athlete_calendar_write":True,"provider_write_count":0}
    print(json.dumps(output,ensure_ascii=False),flush=True)
    return 0 if (not missing and not extra and len(native)==27 and sum(observed.values())==276 and
                 len(mon)==23 and len(sat_bike)==23) else 9

if __name__=="__main__":
    try:raise SystemExit(asyncio.run(run()))
    except Exception as e:
        print(json.dumps({"stage":"STOP_QA","reason":str(e)[:250]},ensure_ascii=False),flush=True)
        raise
