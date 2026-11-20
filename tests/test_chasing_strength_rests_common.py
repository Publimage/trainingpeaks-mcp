from scripts.ironman_jobs.chasing_strength_rests_common import REST,LIB_ID,apply,assert_correct
import pytest
def _mk(key):
 blocks=[{"blockType":"WarmUp","prescriptions":[{"coachNotes":"WU"} for _ in range(3)]}]
 for between,_ in REST[key]:
  n=2 if between else 1
  blocks.append({"blockType":"SingleExercise","prescriptions":[{"coachNotes":"RIR 4","sets":[{"parameterValues":[{"parameter":"Reps","prescribedValue":"5"}]} for _ in range(n)]}]})
 return {"workoutType":"StructuredStrength","prescribedDurationInSeconds":None,"blocks":blocks,"title":"x"}
def test_seven_distinct_phenotypes_and_no_global_time():
 assert set(REST)==set(LIB_ID)
 assert [len(REST[x]) for x in ("A60","B60","S60","M60","D40","M45","M30")]==[8,8,8,7,6,6,5]
 for k in REST:
  original=_mk(k)
  result=apply(original,k)
  assert assert_correct(original,result,k)
  assert result["prescribedDurationInSeconds"] is None
  assert result["blocks"][1]["prescriptions"][0]["coachNotes"].startswith("RIR 4")
  assert apply is not None
  with pytest.raises(ValueError):
   apply(result,k)
