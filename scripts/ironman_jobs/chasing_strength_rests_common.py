"""Coach-approved CHASING Strength: specific inter-set and between-exercise recoveries.
This ONLY changes Coach Notes inside StructuredStrength. No session duration,
exercise, set/reps/RIR, title, IDs, or workout date edits.
Rest windows are based on existing canonical A/B/S/M/D purpose, exercise dose,
RIR and source rest. The intervals are COACH cues, not provider timers.
"""
from __future__ import annotations
import copy,json
MARKER="\n\nRECUPERI OPERATIVI |"
# Per native strength exercise block AFTER warm-up: (rest between work sets; recovery
# AFTER finishing the exercise before beginning next exercise). None = not applicable.
REST={
"A60":[("120-180 s","120-180 s"),("120-180 s","120 s"),(None,"75-90 s"),
       ("60-90 s","75-90 s"),("60-90 s","75-90 s"),("60-90 s","60 s"),
       ("30-45 s","45-60 s"),(None,None)],
"B60":[(None,"90 s"),("90 s","75-90 s"),("60-90 s","60-75 s"),
       ("60-90 s","60-75 s"),("60-90 s","60-75 s"),("60-75 s","45-60 s"),
       (None,"45 s"),(None,None)],
"S60":[("150-180 s","150-180 s"),("150-180 s","120-150 s"),
       (None,"90-120 s"),("75-90 s","90 s"),("90 s","75-90 s"),
       ("75-90 s","60 s"),(None,"45 s"),(None,None)],
"M60":[("120-180 s","120-150 s"),(None,"120 s"),(None,"90 s"),
       (None,"75 s"),("60-90 s","75 s"),(None,"60 s"),(None,None)],
"D40":[(None,"75-90 s"),(None,"60 s"),(None,"60 s"),
       (None,"60 s"),(None,"45-60 s"),(None,None)],
"M45":[("120-180 s","120 s"),(None,"90-120 s"),(None,"60 s"),
       (None,"60 s"),(None,"60 s"),(None,None)],
"M30":[(None,"120 s"),(None,"60-75 s"),(None,"60 s"),
       (None,"45-60 s"),(None,None)],
}
LIB_ID={"A60":"330618","B60":"330621","S60":"330631","M60":"330624",
        "D40":"330626","M45":"330628","M30":"330629"}
WORKOUT_RULES={"A60":"adattamento generale; RIR 4-5; preservare controllo e tecnica",
 "B60":"complementare prima del lungo bici; RIR 4-5; non generare DOMS",
 "S60":"sviluppo forza; 3-5 reps nei fondamentali; RIR 2-3 e recupero neurale pieno",
 "M60":"mantenimento iniziale; RIR 3-4; qualita di esecuzione prima della fretta",
 "D40":"scarico tecnico; nessuna serie a cedimento; recuperi sufficienti senza densita forzata",
 "M45":"mantenimento specifico; riduzione dose, senza rincorrere affaticamento",
 "M30":"richiamo minimo; singoli set non a cedimento; recupero completo tra movimenti"}

def rest_note(text,between,after,*,multilateral=False):
    if text is None:text=""
    if MARKER in text:
        raise ValueError("REST_MARKER_ALREADY_PRESENT")
    a=("tra le serie "+between if between else "serie unica, recupero tra serie non applicabile")
    b=("dopo aver completato l'esercizio, prima del successivo "+after
       if after else "ultimo esercizio: termina la seduta, non aggiungere recuperi artificiali")
    side=("; nei movimenti unilaterali completa entrambi i lati prima di contare la pausa"
          if multilateral else "")
    return text+MARKER+" "+a+"; "+b+side+"."

def apply(workout:dict,key:str)->dict:
    assert key in REST
    w=copy.deepcopy(workout)
    blocks=w.get("blocks")
    if not isinstance(blocks,list) or len(blocks)!=len(REST[key])+1:
        raise ValueError("STRUCTURE_BLOCK_COUNT_CHANGED")
    warm=blocks[0]
    if warm.get("blockType")!="WarmUp":
        raise ValueError("MISSING_WARMUP")
    # Do not change workout.instructions or top-level time.
    warm_text="Tra i 3 esercizi del warm-up: 10-20 s per cambiare posizione; prima del primo esercizio con carico: 60-90 s per predisporre il peso, senza affaticarsi."
    for p in warm.get("prescriptions") or []:
        txt=p.get("coachNotes") or ""
        if MARKER in txt:raise ValueError("WARMUP_ALREADY_DONE")
        p["coachNotes"]=txt+MARKER+" "+warm_text
    for i,((between,after),b) in enumerate(zip(REST[key],blocks[1:]),1):
        ps=b.get("prescriptions") or []
        if b.get("blockType")!="SingleExercise" or len(ps)!=1:
            raise ValueError(f"UNEXPECTED_EXERCISE_BLOCK_{key}_{i}")
        p=ps[0]
        sets=p.get("sets") or []
        if between is None and len(sets)!=1:
            raise ValueError(f"REST_SETS_OMITTED_BUT_MULTIPLE_{key}_{i}")
        if between is not None and len(sets)<2:
            raise ValueError(f"REST_SETS_PRESENT_BUT_SINGLE_{key}_{i}")
        bilateral=any(any(v.get("parameter")=="RepsPerSide" for v in s.get("parameterValues") or []) for s in sets)
        p["coachNotes"]=rest_note(p.get("coachNotes"),between,after,multilateral=bilateral)
    return w

def strip_note_deltas(original,updated):
    """Replace only Coach Notes with originals and check all other workout data invariant."""
    w=copy.deepcopy(updated)
    if len(w.get("blocks") or [])!=len(original.get("blocks") or []):return False
    for current,before in zip(w["blocks"],original["blocks"]):
        for p,q in zip(current.get("prescriptions") or [],before.get("prescriptions") or []):
            p["coachNotes"]=q.get("coachNotes")
    w.pop("lastUpdatedAt",None)
    original_copy=copy.deepcopy(original)
    original_copy.pop("lastUpdatedAt",None)
    return w==original_copy

def assert_correct(original,updated,key):
    expected=apply(original,key)
    if updated.get("prescribedDurationInSeconds")!=original.get("prescribedDurationInSeconds"):
        raise ValueError("DURATION_CHANGED")
    if not strip_note_deltas(original,updated):
        raise ValueError("NON_NOTE_FIELDS_CHANGED")
    current=copy.deepcopy(updated)
    current.pop("lastUpdatedAt",None)
    expected.pop("lastUpdatedAt",None)
    if current!=expected:
        raise ValueError("WRONG_REST_NOTES")
    return True
