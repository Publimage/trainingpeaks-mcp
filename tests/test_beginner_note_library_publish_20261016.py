from pathlib import Path
import ast
def test_beginner_note_library_scope():
 s=Path("scripts/ironman_jobs/beginner_note_library_publish_20261016.py").read_text()
 ast.parse(s)
 assert "P=679801" in s and "LIB=3901898" in s
 assert "FIRST IRONMAN 24W | Note | IT" in s
 assert '"NoteTemplate"' in s and '"workoutTypeId":0' in s
 assert "BEGINNER_NOTE_LIBRARY_VERIFIED" in s
 assert 'calendarNote' in s
 assert '_request("DELETE"' not in s and 'workouts/' not in s.split('calendarNote')[0]
