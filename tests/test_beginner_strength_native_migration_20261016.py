from pathlib import Path
import ast
def test_beginner_strength_native_migration_scope():
    s=Path("scripts/ironman_jobs/beginner_strength_native_migration_20261016.py").read_text()
    ast.parse(s)
    assert "P=679801" in s and "EXPECTED_META_COUNT=225" in s
    assert "len(source)==36" in s
    assert "GOLDEN_NATIVE_STRENGTH_PASS" in s
    assert "ALL_36_NATIVE_VERIFIED_BEFORE_DELETE" in s
    assert 'workouts/save' in s and "StructuredStrength" in s
    assert '_request("DELETE"' in s and "_retry_on_401=False" in s
    assert "BEGINNER_STRENGTH_NATIVE_MIGRATION_VERIFIED" in s
    assert "videos_verified" in s
    assert "SOURCE_IDS" in s
