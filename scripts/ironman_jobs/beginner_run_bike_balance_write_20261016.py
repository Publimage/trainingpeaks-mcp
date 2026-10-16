"""BEGINNER 679801 ONLY: seven RUN reductions + seven BI endurance additions.
Approved 2026-10-16. Public plan, price/public state untouched.
Includes a reversible duration golden on private LAB 684206 before production.
"""
import asyncio,copy,hashlib,json,re
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
from tp_mcp.tools.library import _ensure_structure_preview

PLAN=679801; OWNER=2116886; LAB=684206; LAB_WID=3994992835
BASE=Path.home()/".trainingpeaks-mcp"
BACKUP=BASE/"beginner679801_run_bike_balance_20261016_before.json"
LAB_BACKUP=BASE/"beginner679801_duration_golden_lab_20261016_before.json"
# week: run id, run old,new, bike id,bike old,new, bike mode
ROWS={
13:(3978611963,120,110,3978611934,64,74,"extend"),
14:(3978612079,125,115,3978611998,86,96,"extend"),
15:(3978611986,130,120,3978612017,85,95,"extend"),
17:(3978612028,130,115,3978612020,95,110,"insert"),
18:(3978612029,135,110,3978611970,94,119,"insert"),
19:(3978612039,140,120,3978611958,70,90,"extend"),
21:(3978612034,120,105,3978612108,80,95,"insert"),
}
def need(ok,msg):
    if not ok: raise RuntimeError(msg)
def stable(w): return {k:v for k,v in w.items() if k!="lastModifiedDate"}
def digest(v): return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def seconds(st):
    total=0
    for g in st.get("structure") or []:
        reps=int((g.get("length") or {}).get("value",1)) if g.get("type")=="repetition" else 1
        for z in g.get("steps") or []:
            ln=z.get("length") or {}
            need(ln.get("unit")=="second" and isinstance(ln.get("value"),(int,float)),"NON_DURATION_STEP")
            total += reps*ln["value"]
    return total
def target_range(z):
    t=z.get("targets") or []
    need(len(t)==1 and isinstance(t[0].get("minValue"),(int,float)) and isinstance(t[0].get("maxValue"),(int,float)),"BAD_TARGET")
    return t[0]["minValue"],t[0]["maxValue"]
def entries(st):
    out=[]
    for gi,g in enumerate(st.get("structure") or []):
        reps=int((g.get("length") or {}).get("value",1)) if g.get("type")=="repetition" else 1
        for si,z in enumerate(g.get("steps") or []):
            out.append((gi,si,reps,z))
    return out
def low_easy_candidates(st):
    c=[]
    for gi,si,reps,z in entries(st):
        if reps!=1 or z.get("intensityClass")!="active": continue
        ln=z.get("length") or {}
        if ln.get("unit")!="second" or not isinstance(ln.get("value"),(int,float)): continue
        lo,hi=target_range(z)
        if hi<=3.5:
            c.append((ln["value"],gi,si,z))
    return sorted(c,reverse=True,key=lambda x:x[0])
def choose_easy(st,wid):
    c=low_easy_candidates(st)
    need(c,"NO_LOW_EASY_STEP_"+str(wid))
    top=c[0]
    if len(c)>1: need(top[0]>c[1][0],"AMBIGUOUS_LOW_EASY_STEP_"+str(wid))
    return top[1],top[2]
def text_total_only(s,old,new):
    if not isinstance(s,str) or not s: return s
    pats=[
      (rf"(?i)(\bTotale\s+){old}(\s*(?:minuti|min|'|’))",rf"\g<1>{new}\g<2>"),
      (rf"(?i)(\bdurata(?:\s+totale)?\s*[:=]?\s*){old}(\s*(?:minuti|min|'|’))",rf"\g<1>{new}\g<2>"),
    ]
    out=s
    for p,r in pats: out=re.sub(p,r,out)
    return out
def patch_run(w,old,new):
    wid=w["workoutId"]; need(w.get("workoutTypeValueId")==3,"RUN_SPORT_DRIFT_"+str(wid))
    need(abs((w.get("totalTimePlanned") or 0)*60-old)<.02,"RUN_DURATION_DRIFT_"+str(wid))
    st=copy.deepcopy(w.get("structure") or {})
    need(st.get("primaryLengthMetric")=="duration" and st.get("primaryIntensityMetric")=="rpe","RUN_METRIC_DRIFT_"+str(wid))
    need(seconds(st)==round(old*60),"RUN_BUILDER_SUM_DRIFT_"+str(wid))
    gi,si=choose_easy(st,wid); z=st["structure"][gi]["steps"][si]
    delta=(old-new)*60
    need(z["length"]["value"]>delta+300,"RUN_EASY_TOO_SHORT_"+str(wid))
    before_reps=[copy.deepcopy(g) for g in st["structure"] if g.get("type")=="repetition"]
    z["length"]["value"]-=delta
    st.pop("polyline",None); st=_ensure_structure_preview(st)
    need(seconds(st)==round(new*60),"RUN_NEW_SUM_"+str(wid))
    need([g for g in st["structure"] if g.get("type")=="repetition"]==before_reps,"RUN_REPETITIONS_CHANGED_"+str(wid))
    q=copy.deepcopy(w); q["structure"]=st; q["totalTimePlanned"]=new/60
    q["title"]=text_total_only(q.get("title"),old,new)
    q["description"]=text_total_only(q.get("description"),old,new)
    need(len(st.get("polyline") or [])>=4,"RUN_POLYLINE_MISSING_"+str(wid))
    return q
def patch_bike(w,old,new,mode):
    wid=w["workoutId"]; need(w.get("workoutTypeValueId")==2,"BIKE_SPORT_DRIFT_"+str(wid))
    need(abs((w.get("totalTimePlanned") or 0)*60-old)<.02,"BIKE_DURATION_DRIFT_"+str(wid))
    st=copy.deepcopy(w.get("structure") or {})
    need(st.get("primaryLengthMetric")=="duration" and st.get("primaryIntensityMetric")=="rpe","BIKE_METRIC_DRIFT_"+str(wid))
    need(seconds(st)==round(old*60),"BIKE_BUILDER_SUM_DRIFT_"+str(wid))
    before_reps=[copy.deepcopy(g) for g in st["structure"] if g.get("type")=="repetition"]
    add=(new-old)*60
    if mode=="extend":
        gi,si=choose_easy(st,wid)
        st["structure"][gi]["steps"][si]["length"]["value"]+=add
    else:
        need(mode=="insert","BAD_MODE")
        # Insert a standalone low-intensity endurance block immediately before cooldown.
        cool=[i for i,g in enumerate(st["structure"]) if any(z.get("intensityClass")=="coolDown" for z in g.get("steps") or [])]
        need(len(cool)==1,"COOLDOWN_GROUP_AMBIGUOUS_"+str(wid))
        block={"type":"step","length":{"value":1,"unit":"repetition"},"steps":[{
            "name":"Endurance facile","intensityClass":"active","targets":[{"minValue":2,"maxValue":3}],
            "length":{"value":add,"unit":"second"},"openDuration":False
        }]}
        st["structure"].insert(cool[0],block)
    st.pop("polyline",None); st=_ensure_structure_preview(st)
    need(seconds(st)==round(new*60),"BIKE_NEW_SUM_"+str(wid))
    need([g for g in st["structure"] if g.get("type")=="repetition"]==before_reps,"BIKE_REPETITIONS_CHANGED_"+str(wid))
    q=copy.deepcopy(w); q["structure"]=st; q["totalTimePlanned"]=new/60
    q["title"]=text_total_only(q.get("title"),old,new)
    q["description"]=text_total_only(q.get("description"),old,new)
    need(len(st.get("polyline") or [])>=4,"BIKE_POLYLINE_MISSING_"+str(wid))
    return q
async def plan_head(c,p):
    r=await c.get(f"/plans/v1/plans/{p}"); need(not r.is_error and isinstance(r.data,dict),"PLAN_READ_"+str(p)); return r.data
async def week_read(c,p,anchor,wk):
    a=anchor+timedelta(weeks=wk-1); b=a+timedelta(days=6)
    rw=await c.get(f"/plans/v1/plans/{p}/workouts/{a.isoformat()}/{b.isoformat()}")
    rn=await c.get(f"/plans/v1/plans/{p}/calendarNote/{a.isoformat()}/{b.isoformat()}")
    need(not rw.is_error and not rn.is_error and isinstance(rw.data,list) and isinstance(rn.data,list),"WEEK_READ_"+str(p)+"_"+str(wk))
    return rw.data,rn.data
async def lab_golden(c):
    h=await plan_head(c,LAB)
    need(h.get("planId")==LAB and h.get("isPublic") is False and h.get("workoutCount")==6 and "[MCP TEST]" in (h.get("title") or ""),"LAB_GUARD")
    anchor=date.fromisoformat(str(h["startDate"])[:10]); arr,notes=await week_read(c,LAB,anchor,1)
    w=next((x for x in arr if x.get("workoutId")==LAB_WID),None); need(w is not None,"LAB_TARGET_MISSING")
    original=copy.deepcopy(w); st=copy.deepcopy(w.get("structure") or {})
    need(st.get("primaryIntensityMetric")=="rpe" and seconds(st)==2700,"LAB_SOURCE_DRIFT")
    cds=[(gi,si,z) for gi,si,reps,z in entries(st) if reps==1 and z.get("intensityClass")=="coolDown" and (z.get("length") or {}).get("unit")=="second"]
    need(len(cds)==1 and cds[0][2]["length"]["value"]==300,"LAB_COOLDOWN_DRIFT")
    gi,si,_=cds[0]; st["structure"][gi]["steps"][si]["length"]["value"]=600
    st.pop("polyline",None); st=_ensure_structure_preview(st)
    trial=copy.deepcopy(w); trial["structure"]=st; trial["totalTimePlanned"]=50/60
    res=await c._request("PUT",f"/plans/v1/plans/{LAB}/workouts/{LAB_WID}",json=trial,_retry_on_401=False)
    after,notes2=await week_read(c,LAB,anchor,1); now=next(x for x in after if x.get("workoutId")==LAB_WID)
    need(not res.is_error and stable(now)==stable(trial) and digest(notes2)==digest(notes),"LAB_GOLDEN_WRITE_FAIL")
    res2=await c._request("PUT",f"/plans/v1/plans/{LAB}/workouts/{LAB_WID}",json=original,_retry_on_401=False)
    restored,notes3=await week_read(c,LAB,anchor,1); rr=next(x for x in restored if x.get("workoutId")==LAB_WID)
    need(not res2.is_error and stable(rr)==stable(original) and digest(notes3)==digest(notes),"LAB_RESTORE_FAIL")
    print(json.dumps({"stage":"LAB_DURATION_GOLDEN_PASS","plan":LAB,"workout":LAB_WID,"45_to_50_and_restore":True,"provider_writes":2}),flush=True)
async def main():
    async with TPClient() as c:
        me=await c._get_user_data(); need(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        await lab_golden(c)
        h=await plan_head(c,PLAN)
        need(h.get("planId")==PLAN and h.get("isPublic") is True and h.get("workoutCount")==254 and "Beginner" in (h.get("title") or ""),"PUBLIC_PLAN_GUARD")
        anchor=date.fromisoformat(str(h["startDate"])[:10])
        weeks=sorted(ROWS)
        live={}; week_baseline={}; notehash={}
        for wk in weeks:
            arr,notes=await week_read(c,PLAN,anchor,wk)
            week_baseline[wk]={x["workoutId"]:stable(x) for x in arr}
            notehash[wk]=digest(notes)
            for x in arr: live[x["workoutId"]]=x
        targets=set()
        desired={}
        for wk,(rid,ro,rn,bid,bo,bn,mode) in ROWS.items():
            targets|={rid,bid}
            need(rid in live and bid in live,"TARGET_MISSING_W"+str(wk))
            desired[rid]=patch_run(live[rid],ro,rn)
            desired[bid]=patch_bike(live[bid],bo,bn,mode)
        need(len(targets)==14 and set(desired)==targets,"TARGET_COUNT")
        # Exact weekly zero-balance.
        for wk,(rid,ro,rn,bid,bo,bn,mode) in ROWS.items():
            need((rn-ro)+(bn-bo)==0,"WEEK_BALANCE_"+str(wk))
        # Backup / recovery: only original or desired states are accepted.
        originals={wid:stable(live[wid]) for wid in targets}
        if BACKUP.exists():
            saved=json.loads(BACKUP.read_text())
            need(saved.get("plan")==PLAN and set(map(int,saved.get("target_ids",[])))==targets,"BACKUP_SCOPE_DRIFT")
            originals={int(k):v for k,v in saved["originals"].items()}
        else:
            BASE.mkdir(parents=True,exist_ok=True)
            BACKUP.write_text(json.dumps({"plan":PLAN,"owner":OWNER,"target_ids":sorted(targets),"originals":originals,
                "notehash":notehash,"scope":"BEGINNER_RUN_BIKE_DURATION_BALANCE_ONLY"},ensure_ascii=False,default=str,indent=2)+"\n")
        expected={}
        for wk in weeks: expected.update(week_baseline[wk])
        for wid in targets:
            cur=stable(live[wid]); des=stable(desired[wid]); orig=originals[wid]
            need(cur==orig or cur==des,"UNKNOWN_TARGET_DRIFT_"+str(wid))
            if cur==des: expected[wid]=des
        print(json.dumps({"stage":"PRODUCTION_PREFLIGHT_PASS","plan":PLAN,"targets":14,"weeks":weeks,
            "run_delta_min":-105,"bike_delta_min":105,"weekly_balance_zero":True,"public_plan":True,
            "price_or_visibility_fields_modified":False}),flush=True)
        order=[]
        for wk in weeks:
            rid,ro,rn,bid,bo,bn,mode=ROWS[wk]; order += [rid,bid]
        written=0
        for wid in order:
            # Re-read only target week immediately before each PUT.
            wk=next(k for k,v in ROWS.items() if wid in (v[0],v[3]))
            arr,notes=await week_read(c,PLAN,anchor,wk); current={x["workoutId"]:stable(x) for x in arr}
            need(digest(notes)==notehash[wk],"NOTES_DRIFT_W"+str(wk))
            for k,v in current.items():
                if k==wid: continue
                need(v==expected.get(k,v),"UNRELATED_PREWRITE_DRIFT_"+str(k))
            if current[wid]==stable(desired[wid]):
                expected[wid]=stable(desired[wid]); continue
            need(current[wid]==originals[wid],"TARGET_PREWRITE_DRIFT_"+str(wid))
            res=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",json=desired[wid],_retry_on_401=False)
            after,notes2=await week_read(c,PLAN,anchor,wk); now={x["workoutId"]:stable(x) for x in after}
            if now.get(wid)!=stable(desired[wid]):
                need(current[wid]==now.get(wid),"AMBIGUOUS_WRITE_STATE_"+str(wid))
                need(not res.is_error,"PROVIDER_WRITE_FAILED_"+str(wid))
                raise RuntimeError("WRITE_NOT_APPLIED_"+str(wid))
            need(digest(notes2)==notehash[wk],"NOTES_CHANGED_"+str(wid))
            expected[wid]=stable(desired[wid])
            need(all(now[k]==expected.get(k,now[k]) for k in now),"UNRELATED_POSTWRITE_DRIFT_"+str(wid))
            written+=1
            print(json.dumps({"stage":"WRITE_VERIFIED","id":wid,"week":wk,"written_this_run":written}),flush=True)
        # Final target-week reconciliation and native sums.
        for wk,(rid,ro,rn,bid,bo,bn,mode) in ROWS.items():
            arr,notes=await week_read(c,PLAN,anchor,wk); curr={x["workoutId"]:x for x in arr}
            need(digest(notes)==notehash[wk],"FINAL_NOTES_DRIFT_"+str(wk))
            need(stable(curr[rid])==stable(desired[rid]) and stable(curr[bid])==stable(desired[bid]),"FINAL_TARGET_DRIFT_"+str(wk))
            need(abs(curr[rid]["totalTimePlanned"]*60-rn)<.02 and seconds(curr[rid]["structure"])==rn*60,"FINAL_RUN_DURATION_"+str(wk))
            need(abs(curr[bid]["totalTimePlanned"]*60-bn)<.02 and seconds(curr[bid]["structure"])==bn*60,"FINAL_BIKE_DURATION_"+str(wk))
        h2=await plan_head(c,PLAN)
        need(h2.get("isPublic") is True and h2.get("workoutCount")==254,"PLAN_METADATA_CHANGED")
        print(json.dumps({"stage":"BEGINNER_RUN_BIKE_BALANCE_VERIFIED","plan":PLAN,"targets":14,
            "written_this_run":written,"run_delta_min":-105,"bike_delta_min":105,
            "weekly_balance_zero":True,"workout_count":254,"public_state_preserved":True,
            "other_week_workouts_preserved":True,"calendar_notes_preserved":True}),flush=True)
if __name__=="__main__":
    try: asyncio.run(main())
    except Exception as e:
        print(json.dumps({"stage":"SAFE_STOP","reason":str(e)[:500]}),flush=True)
        raise
