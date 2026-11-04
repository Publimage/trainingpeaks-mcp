import unittest
from scripts.ironman_jobs.coaching_radar_polverari_v0 import triage


class RadarTests(unittest.TestCase):
    def test_tss_quality_not_overload(self):
        workouts = [{"id": "3997494824", "date": "2026-10-15", "sport": "Run",
                     "type": "completed", "duration_planned": 35/60,
                     "duration_actual": 35.19/60, "tss_planned": 44.99,
                     "tss_actual": 118.79}]
        r = triage(workouts, 2932097, "2026-10-15")
        self.assertEqual(r["alerts"][0]["category"], "TSS_DATA_QUALITY")
        self.assertEqual(r["alerts"][0]["severity"], "YELLOW")
        self.assertEqual(r["trainingpeaks_writes"], 0)

    def test_future_not_missing(self):
        w = [{"id": "a", "date": "2026-10-16", "type": "planned",
              "sport": "Bike", "title": "75 min"}]
        r = triage(w, 2932097, "2026-10-15")
        self.assertFalse(r["alerts"])
        self.assertEqual(len(r["upcoming"]), 1)

    def test_other_and_today_planned_not_flagged(self):
        w = [{"id": "b", "date": "2026-10-14", "type": "planned", "sport": "Other"},
             {"id": "c", "date": "2026-10-15", "type": "planned", "sport": "Run"}]
        self.assertFalse(triage(w, 2932097, "2026-10-15")["alerts"])

    def test_wrong_athlete_stops(self):
        with self.assertRaises(ValueError):
            triage([], 111, "2026-10-15")

    def test_duplicate_id_stops(self):
        w = {"id": "x", "date": "2026-10-15", "type": "planned", "sport": "Run"}
        with self.assertRaises(ValueError):
            triage([w, w], 2932097, "2026-10-15")


if __name__ == "__main__":
    unittest.main()
