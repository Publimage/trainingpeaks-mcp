"""Provider-free QA for the reusable plan publisher. No live TrainingPeaks writes."""
import asyncio
import copy
import json

import pytest

from scripts.ironman_jobs.plan_patch_batch_core import PlanPatchStop
from scripts.ironman_jobs.reviewed_plan_patch_pipeline import load_config, publish


class FakeTP:
    def __init__(self):
        self.person_id = 2116886
        self.meta = {
            "planId": 777, "title": "LAB | Controlled future release",
            "isPublic": True, "workoutCount": 2,
        }
        self.rows = [
            {"workoutId": 11, "workoutTypeValueId": 2, "workoutDay": "2027-03-10T00:00:00",
             "title": "BIKE | Old", "description": "Leave unchanged", "structure": {"x": 1}},
            {"workoutId": 12, "workoutTypeValueId": 3, "workoutDay": "2027-03-12T00:00:00",
             "title": "RUN | Keep", "description": "Do not modify", "structure": {"z": 2}},
        ]
        self.notes = [{"calendarNoteId": 991, "title": "Existing weekly note"}]
        self.writes = []
        self.force_refuse = False
        self.mutate_unrelated = False

    async def _get_user_data(self):
        return {"personId": self.person_id}

    async def get(self, endpoint):
        from types import SimpleNamespace
        if endpoint == "/plans/v1/plans/777":
            return SimpleNamespace(is_error=False, data=copy.deepcopy(self.meta))
        if endpoint == "/plans/v1/plans/777/workouts/2027-03-01/2027-03-31":
            return SimpleNamespace(is_error=False, data=copy.deepcopy(self.rows))
        if endpoint == "/plans/v1/plans/777/calendarNote/2027-03-01/2027-03-31":
            return SimpleNamespace(is_error=False, data=copy.deepcopy(self.notes))
        return SimpleNamespace(is_error=True, data=None)

    async def _request(self, method, endpoint, json=None, _retry_on_401=True):
        from types import SimpleNamespace
        self.writes.append((method, endpoint, copy.deepcopy(json), _retry_on_401))
        if self.force_refuse:
            return SimpleNamespace(is_error=True, error_code="AUTH_INVALID")
        assert method == "PUT" and endpoint == "/plans/v1/plans/777/workouts/11"
        self.rows[0] = copy.deepcopy(json)
        if self.mutate_unrelated:
            self.rows[1]["description"] = "UNEXPECTED"
        return SimpleNamespace(is_error=False, error_code=None)


def config():
    return {
        "schema": "IRONMAN_REVIEWED_PLAN_PATCH_CONFIG_V1",
        "configured": True,
        "windows": [["2027-03-01", "2027-03-31"]],
        "expected_classic_count": 2,
        "expected_note_count": 1,
        "manifest": {
            "schema": "IRONMAN_PLAN_PATCH_V1",
            "owner_id": 2116886,
            "plan_id": 777,
            "expected_title": "LAB | Controlled future release",
            "expected_is_public": True,
            "expected_workout_count": 2,
            "scope": "trainingpeaks:plan:777:future-workout-title-approved",
            "items": [{
                "workout_id": 11,
                "expected_sport_id": 2,
                "expected_workout_day": "2027-03-10",
                "before": {"title": "BIKE | Old"},
                "after": {"title": "BIKE | New"},
            }]
        }
    }


def write_conf(tmp_path, cfg=None):
    file = tmp_path / "approved.json"
    file.write_text(json.dumps(cfg or config()), encoding="utf-8")
    return file


def go(fake, tmp_path, *, execute=False, cfg=None):
    return asyncio.run(publish(
        execute=execute, config_path=write_conf(tmp_path, cfg),
        client=fake, journal_dir=tmp_path / "journal"
    ))


def test_future_manifest_preview_is_strictly_read_only(tmp_path):
    client = FakeTP()
    result = go(client, tmp_path)
    assert result["stage"] == "PLAN_PATCH_PREVIEW_PASS"
    assert result["targets"] == 1 and result["workouts_total"] == 2
    assert result["notes_total"] == 1 and result["provider_writes"] == 0
    assert not client.writes
    assert not (tmp_path / "journal").exists()


def test_permitted_reusable_writer_changes_only_one_title_and_reads_back(tmp_path):
    client = FakeTP()
    original_note = copy.deepcopy(client.notes)
    untouched = copy.deepcopy(client.rows[1])
    result = go(client, tmp_path, execute=True)
    assert result["stage"] == "PLAN_PATCH_PUBLISH_VERIFIED"
    assert result["provider_writes"] == 1
    assert result["public_preserved"] is True
    assert client.rows[0]["title"] == "BIKE | New"
    assert client.rows[0]["description"] == "Leave unchanged"
    assert client.rows[0]["structure"] == {"x": 1}
    assert client.rows[1] == untouched and client.notes == original_note
    assert client.writes[0][3] is False
    replay = go(client, tmp_path, execute=True)
    assert replay["provider_writes"] == 0 and len(client.writes) == 1


def test_no_active_manifest_stops_before_provider(tmp_path):
    client = FakeTP()
    f = tmp_path / "none.json"
    f.write_text(json.dumps({"schema": "IRONMAN_REVIEWED_PLAN_PATCH_CONFIG_V1",
                             "configured": False}), encoding="utf-8")
    with pytest.raises(PlanPatchStop, match="MANIFEST_NOT_YET_CONFIGURED"):
        load_config(f)
    assert not client.writes


def test_unreviewed_plan_or_owner_is_rejected(tmp_path):
    client = FakeTP()
    cfg = config()
    cfg["manifest"]["plan_id"] = 888
    with pytest.raises(PlanPatchStop, match="SCOPE_MUST_BIND_PLAN_ID"):
        go(client, tmp_path, cfg=cfg)
    client.person_id = 41
    with pytest.raises(PlanPatchStop, match="WRONG_COACH"):
        go(client, tmp_path)
    assert not client.writes


def test_bad_visibility_counts_and_sport_stop_before_put(tmp_path):
    client = FakeTP()
    client.meta["isPublic"] = False
    with pytest.raises(PlanPatchStop, match="PLAN_METADATA_CHANGED"):
        go(client, tmp_path, execute=True)
    client.meta["isPublic"] = True
    cfg = config()
    cfg["expected_note_count"] = 0
    with pytest.raises(PlanPatchStop, match="NOTE_COUNT_DRIFT"):
        go(client, tmp_path, execute=True, cfg=cfg)
    cfg = config()
    cfg["manifest"]["items"][0]["expected_sport_id"] = 3
    with pytest.raises(PlanPatchStop, match="SPORT_SCOPE_MISMATCH"):
        go(client, tmp_path, execute=True, cfg=cfg)
    assert not client.writes


def test_forbidden_provider_response_no_automatic_replay(tmp_path):
    client = FakeTP()
    client.force_refuse = True
    with pytest.raises(PlanPatchStop, match="UNCERTAIN_RESULT"):
        go(client, tmp_path, execute=True)
    assert len(client.writes) == 1
    assert client.rows[0]["title"] == "BIKE | Old"
    client.force_refuse = False
    with pytest.raises(PlanPatchStop, match="RECONCILE_FIRST"):
        go(client, tmp_path, execute=True)
    assert len(client.writes) == 1


def test_non_target_workout_tampering_detected(tmp_path):
    client = FakeTP()
    client.mutate_unrelated = True
    with pytest.raises(PlanPatchStop, match="NON_TARGET_CHANGED"):
        go(client, tmp_path, execute=True)
    assert len(client.writes) == 1


def test_invalid_window_or_extraneous_manifest_fields(tmp_path):
    bad = config()
    bad["windows"] = [["2027-03-31", "2027-03-01"]]
    with pytest.raises(PlanPatchStop, match="WINDOW_TOO_WIDE"):
        load_config(write_conf(tmp_path, bad))
    bad = config()
    bad["unsafe_api_path"] = "/users/v3/user"
    with pytest.raises(PlanPatchStop, match="CONFIG_UNEXPECTED_FIELDS"):
        load_config(write_conf(tmp_path, bad))


def test_missing_target_or_unapproved_change(tmp_path):
    client = FakeTP()
    client.rows[0]["title"] = "Coach edited it"
    with pytest.raises(PlanPatchStop, match="PREVIEW_TARGET_DRIFT"):
        go(client, tmp_path, execute=True)
    assert not client.writes
