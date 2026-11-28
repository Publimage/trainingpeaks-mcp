from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/workout_library_classic_organization_canary.py"
def test_exact_lab_scope_and_roundtrip():
    s=P.read_text();ast.parse(s)
    assert "SOURCE_LIB=3890637" in s
    assert "SOURCE_ITEM=14935062" in s
    assert "[MCP TEST] Organization Library Canary" in s
    assert "/exerciselibrary/v1/libraries/{tid}/name" in s
    assert "/exerciselibrary/v1/libraries/{tid}/items" in s
    assert '"/exerciselibrary/v1/libraries/{tid}/items/{copied_id}"' in s
    assert '"/exerciselibrary/v1/libraries/{tid}/items/{SOURCE_ITEM}"' in s
    assert '"/exerciselibrary/v1/libraries/{SOURCE_LIB}/items/{SOURCE_ITEM}"' in s
    assert s.count("_retry_on_401=False") >= 6
    assert "SOURCE_ITEM_NOT_EXACTLY_RESTORED" in s
    assert "COMPLETE_VERIFIED" in s
    assert "/fitness/" not in s and "/plans/" not in s
