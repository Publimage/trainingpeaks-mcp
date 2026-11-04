"""IRONMAN Coaching Radar v0: pure, read-only workout triage.

No network, credentials, athlete writes, or Prefect deployment in this module.
Input is normalized tp_get_workouts data. Hours and TSS follow TP MCP semantics.
"""
from __future__ import annotations

from datetime import date
from typing import Any

ENDURANCE = {"Swim", "Bike", "Run"}
AUXILIARY = {"Other", "DayOff", "Custom"}


def triage(workouts: list[dict[str, Any]], athlete_id: int, as_of: str) -> dict[str, Any]:
    today = date.fromisoformat(as_of)
    if athlete_id != 2932097:
        raise ValueError("PILOT_ATHLETE_ID_MISMATCH")
    alerts: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    seen: set[str] = set()
    for w in workouts:
        wid = str(w["id"])
        if wid in seen:
            raise ValueError("DUPLICATE_WORKOUT_ID")
        seen.add(wid)
        day = date.fromisoformat(w["date"])
        sport = w.get("sport")
        if day > today:
            if sport in ENDURANCE or sport == "Strength":
                upcoming.append({"date": str(day), "id": wid, "sport": sport,
                                 "title": w.get("title", ""), "status": w.get("type")})
            continue
        if sport not in ENDURANCE:
            continue
        if w.get("type") == "completed":
            planned = w.get("tss_planned")
            actual = w.get("tss_actual")
            duration_p = w.get("duration_planned")
            duration_a = w.get("duration_actual")
            if isinstance(planned, (int, float)) and planned > 0 and isinstance(actual, (int, float)):
                ratio = actual / planned
                if ratio >= 2.0:
                    alerts.append({"severity": "YELLOW", "category": "TSS_DATA_QUALITY",
                                   "date": str(day), "workout_id": wid, "sport": sport,
                                   "planned_tss": round(planned, 2),
                                   "actual_tss": round(actual, 2),
                                   "ratio": round(ratio, 2),
                                   "reason": "Discrepanza numerica: verificare soglie, sensori, IF e RPE; non inferire sovraccarico"})
            if isinstance(duration_p, (int, float)) and duration_p > 0 and isinstance(duration_a, (int, float)):
                if duration_a / duration_p < 0.75:
                    alerts.append({"severity": "YELLOW", "category": "DURATION_SHORT",
                                   "date": str(day), "workout_id": wid,
                                   "planned_minutes": round(duration_p * 60, 1),
                                   "actual_minutes": round(duration_a * 60, 1)})
        elif w.get("type") == "planned" and day < today:
            alerts.append({"severity": "YELLOW", "category": "COMPLETION_UNCONFIRMED",
                           "date": str(day), "workout_id": wid,
                           "reason": "Seduta senza eseguito associato; non dichiarare automaticamente saltata"})
    return {"schema": "IRONMAN_COACHING_RADAR_V0", "athlete_id": athlete_id,
            "as_of": as_of, "mode": "READ_ONLY", "alerts": alerts,
            "upcoming": sorted(upcoming, key=lambda x: (x["date"], x["id"])),
            "trainingpeaks_writes": 0}
