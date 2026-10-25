from pathlib import Path
import ast

P=Path("scripts/ironman_jobs/chasing_w01_three_builder_only_20261014.py")

def test_canaries_and_scope():
    src=P.read_text()
    tree=ast.parse(src)
    assert "PLAN=685173" in src and "OWNER=2116886" in src and "PERSON=6682479" in src
    for wid in ("4000490146","4000490183","4000490091"):
        assert wid in src
    for key in ("percentOfFtp","percentOfThresholdPace","_ensure_structure_preview"):
        assert key in src
    assert '"PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}"' in src
    assert "BACKUP_EXISTS_VERIFY_BEFORE_RETRY" in src
    assert "UNEXPECTED_OTHER_WORKOUT_CHANGE_" in src
    assert "NO_POST_OR_DELETE" not in src
    assert "tp_update_workout" not in src
    assert "calendar/athlete" not in src
    assert "description]=" not in src and 'q["title"]=' not in src
    assert '"isPublic") is False' in src
    assert '"workoutCount")==276' in src
    assert "no_athlete_writes" in src

def test_exact_target_table():
    mod=ast.parse(P.read_text())
    a=next(n for n in mod.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="CANARIES" for t in n.targets))
    c=ast.literal_eval(a.value)
    assert len(c)==3 and len({x[0] for x in c})==3
    assert c[0]==(4000490146,3,3,35,"percentOfThresholdPace",((76,82),(78,84),(70,78)))
    assert c[1]==(4000490183,2,5,190,"percentOfFtp",((50,60),(60,70),(45,55)))
    assert c[2]==(4000490091,3,6,65,"percentOfThresholdPace",((76,82),(80,86),(70,78)))
