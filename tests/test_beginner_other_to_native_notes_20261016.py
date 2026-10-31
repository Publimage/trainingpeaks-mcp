from pathlib import Path
import ast
def test_beginner_native_notes_migration_scope():
 s=Path("scripts/ironman_jobs/beginner_other_to_native_notes_20261016.py").read_text()
 ast.parse(s)
 assert "P=679801" in s and "EXPECT_OTHER=29" in s and "EXPECT_NATIVE_BEFORE=1" in s
 assert "README FIRST | INIZIA DA QUI" in s
 assert '_request("POST"' in s and 'calendarNote' in s
 assert '_request("DELETE"' in s and 'workouts/{ident}' in s
 assert "_retry_on_401=False" in s
 assert "ALL_NATIVE_NOTES_VERIFIED_BEFORE_DELETE" in s
 assert "BEGINNER_NATIVE_NOTES_MIGRATION_VERIFIED" in s
 assert "isPublic" in s and "225" in s
