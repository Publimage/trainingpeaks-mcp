"""Mandatory reusable IRONMAN swim metadata QA.

Every swim must have positive planned distance (metres) and native planned
duration (hours). Planned source duration is an estimate, not a CSS target.
Pure module: no reads and no writes.
"""
from __future__ import annotations
from collections.abc import Iterable,Mapping
from math import isfinite
from typing import Any

class SwimPrescriptionGateError(ValueError):
    pass

def _positive(v:Any)->bool:
    return isinstance(v,(int,float)) and not isinstance(v,bool) and isfinite(float(v)) and v>0

def audit_swims(workouts:Iterable[Mapping[str,Any]], *, surface:str)->dict[str,Any]:
    if not surface:
        raise ValueError("QA surface required")
    defects=[]
    scanned=0
    for w in workouts:
        if not isinstance(w,Mapping):
            raise SwimPrescriptionGateError("Non-mapping workout record")
        sport=w.get("workoutTypeValueId",w.get("workoutTypeId"))
        if sport not in (1,"1"):
            continue
        scanned+=1
        ident=w.get("workoutId",w.get("exerciseLibraryItemId",w.get("id")))
        issues=[]
        if not _positive(w.get("distancePlanned")):
            issues.append("PLANNED_DISTANCE_METERS_MISSING")
        if not _positive(w.get("totalTimePlanned")):
            issues.append("NATIVE_PLANNED_DURATION_HOURS_MISSING")
        if issues:
            defects.append({"id":ident,"title":w.get("title",w.get("itemName")),
                            "issues":issues})
    if not scanned:
        raise SwimPrescriptionGateError(f"No swimming records verified for {surface}")
    return {"surface":surface,"swim_count":scanned,
            "missing_count":len(defects),"defects":defects,
            "status":"PASS" if not defects else "BLOCK_RELEASE"}

def assert_swim_ready(workouts:Iterable[Mapping[str,Any]],*,surface:str)->dict[str,Any]:
    report=audit_swims(workouts,surface=surface)
    if report["status"]!="PASS":
        raise SwimPrescriptionGateError(str(report))
    return report
