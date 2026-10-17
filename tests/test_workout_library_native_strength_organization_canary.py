from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/workout_library_native_strength_organization_canary.py"
def test_native_routes_and_scope():
    s=P.read_text();ast.parse(s)
    assert "SOURCE_LIB=3890637" in s
    assert "SOURCE_ID=330612" in s
    assert "/rx/activity/v1/libraryContent/workoutLibrary/save" in s
    assert "/rx/activity/v1/libraryContent/workoutLibrary/items/{item_id}" in s
    assert "/rx/activity/v1/LibraryContent/workoutLibrary/items/copy" in s
    assert "StructuredStrength" in s
    assert "NATIVE_MOVE_BACK_VERIFIED" in s
    assert "NATIVE_SOURCE_NOT_EXACTLY_RESTORED" in s
    assert s.count("_retry_on_401=False") >= 2
    assert "/fitness/" not in s and "/plans/" not in s
