"""Unit tests for preview and locale invalidation: no provider writes."""
import unittest
from field_edits import Edit, Record, ScopeError, preview, invalidate_translations, digest, apply_text


class FieldEditTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            Record("s1", "training_plan_workout", 1, "swimming", 1001, "it-IT", {"title": "Test | Nuoto", "description": "Esegui 4x100"}),
            Record("b1", "training_plan_workout", 1, "cycling", 1002, "it-IT", {"title": "Lungo | Bici", "description": "RPE 4"}),
            Record("s2", "training_plan_workout", 2, "swimming", 1003, "it-IT", {"title": "Aerobico | Nuoto", "description": "Facile"}),
        ]

    def run_preview(self, **kwargs):
        return preview(self.rows, resource="training_plan_workout", locale="it-IT", **kwargs)

    def test_swim_only(self):
        r = self.run_preview(expected_count=2, edit=Edit("title","prepend",text="A | "), sports=["nuoto"])
        self.assertEqual([v["uid"] for v in r["diffs"]], ["s1", "s2"])
        self.assertEqual(r["provider_writes"], 0)

    def test_weeks(self):
        self.assertEqual(self.run_preview(expected_count=1, edit=Edit("title","set",text="New"), weeks=[2])["selected"], 1)

    def test_uid(self):
        self.assertEqual(self.run_preview(expected_count=1, edit=Edit("title","set",text="New"), uids=["b1"])["diffs"][0]["uid"],"b1")

    def test_full_scope(self):
        self.assertEqual(self.run_preview(expected_count=3, edit=Edit("description","append",text=" Fine."))["selected"],3)

    def test_count_fail_closed(self):
        with self.assertRaises(ScopeError):
            self.run_preview(expected_count=3, edit=Edit("title","set",text="x"), sports=["swim"])

    def test_prefix_idempotent(self):
        self.assertEqual(apply_text("A | Titolo",Edit("title","prepend",text="A | "))[0],"A | Titolo")

    def test_append_idempotent(self):
        self.assertEqual(apply_text("End.",Edit("description","append",text="."))[0],"End.")

    def test_replace_exact(self):
        self.assertEqual(apply_text("A B",Edit("title","replace_text",text="C",find="B"))[0],"A C")

    def test_missing_match_fails(self):
        with self.assertRaises(ScopeError):apply_text("x",Edit("title","replace_text",find="z",text="a"))

    def test_remove_prefix(self):
        self.assertEqual(apply_text("A | Titolo",Edit("title","remove_prefix",text="A | "))[0],"Titolo")

    def test_remove_suffix(self):
        self.assertEqual(apply_text("Titolo V1",Edit("title","remove_suffix",text=" V1"))[0],"Titolo")

    def test_empty_prevented(self):
        with self.assertRaises(ScopeError):apply_text("X",Edit("title","remove_prefix",text="X"))

    def test_structure_not_editable(self):
        with self.assertRaises(ScopeError):self.run_preview(expected_count=1,edit=Edit("structure","set",text="x"),uids=["s1"])

    def test_ambiguous_provider_id(self):
        bad = self.rows + [Record("a4","training_plan_workout",3,"swimming",1001,"it-IT",{"title":"x"})]
        with self.assertRaises(ScopeError):preview(bad,resource="training_plan_workout",locale="it-IT",expected_count=4,edit=Edit("title","set",text="x"))

    def test_duplicate_uid(self):
        bad = self.rows + [Record("s1","training_plan_workout",3,"swimming",9009,"it-IT",{"title":"x"})]
        with self.assertRaises(ScopeError):preview(bad,resource="training_plan_workout",locale="it-IT",expected_count=4,edit=Edit("title","set",text="x"))

    def test_localization_invalidation(self):
        old=[{"uid":"s1","field":"title","locale":"en-US","source_hash":digest("old"),"status":"APPROVED"},
             {"uid":"s2","field":"title","locale":"en-US","source_hash":digest("old"),"status":"APPROVED"}]
        updated=invalidate_translations(old,"s1","title","new")
        self.assertEqual([x["status"] for x in updated],["STALE","APPROVED"])
        self.assertEqual(old[0]["status"],"APPROVED")

    def test_invalid_locale(self):
        with self.assertRaises(ScopeError):preview(self.rows,resource="training_plan_workout",locale="",expected_count=3,edit=Edit("title","set",text="x"))

    def test_note_selection(self):
        note=[Record("note1","training_plan_note",1,"other",55,"it-IT",{"title":"README","description":"Testo"})]
        out=preview(note,resource="training_plan_note",locale="it-IT",expected_count=1,edit=Edit("title","append",text=" FIRST"))
        self.assertEqual(out["diffs"][0]["after"],"README FIRST")

if __name__=="__main__":
    unittest.main()
