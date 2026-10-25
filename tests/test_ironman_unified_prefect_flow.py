"""Prefect flow contract: one entrypoint, synthetic adapter, no live writes."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ironman_jobs.ironman_unified_changeset_engine import ChangeStop, digest
from scripts.ironman_jobs import ironman_unified_prefect_flow as pipeline


def manifest():
    old, new = {"id": 77, "description": "old"}, {"id": 77, "description": "new"}
    return {
        "schema": "IRONMAN_CHANGESET_V1",
        "request_id": "offline-universal-001",
        "owner_id": 2116886,
        "reviewed_revision": "a" * 40,
        "approval_scope": "offline:preview:all-plans",
        "changes": [{
            "id": "change1",
            "kind": "plan.workout.patch",
            "target": {
                "provider": "trainingpeaks", "owner_id": 2116886,
                "container_kind": "training_plan",
                "container_id": 684602, "resource_id": 77,
            },
            "before_sha256": digest(old), "after_sha256": digest(new),
            "depends_on": [], "payload": {"desired": new},
        }]
    }


REQUESTED_TARGET = {
    "kind": "plan.workout.patch",
    "target": {"provider": "trainingpeaks", "owner_id": 2116886,
               "container_kind": "training_plan", "container_id": 684602,
               "resource_id": 77},
}


class SyntheticReadAdapter:
    def read(self, _):
        return {"id": 77, "description": "old"}

    def apply(self, _):
        raise AssertionError("PREVIEW_MUST_NEVER_WRITE")


def test_one_prefect_flow_accepts_generic_manifest_and_previews_only(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "create_read_registry",
                        lambda read_transport="local": {"plan.workout.patch": SyntheticReadAdapter()})
    result = pipeline.unified_changeset_flow(manifest(), str(tmp_path/"ledger.sqlite3"),
                                                 requested_targets=[REQUESTED_TARGET])
    assert result["results"][0]["state"] == "PREFLIGHT_PASS"
    assert result["provider_writes"] == 0
    assert result["publication_enabled"] is False
    assert result["source"] == "trainingpeaks_live_read_only"
    assert pipeline.unified_changeset_flow.name == "ironman-unified-changeset-v1"


def test_refuses_publish_before_any_provider_work(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "create_read_registry",
                        lambda read_transport="local": (_ for _ in ()).throw(AssertionError("SHOULD_NOT_READ")))
    with pytest.raises(ChangeStop, match="PUBLISHING_NOT_YET_ENABLED"):
        pipeline.unified_changeset_flow.fn(
            manifest(), str(tmp_path/"ledger.sqlite3"), mode="publish"
        )
    assert not (tmp_path/"ledger.sqlite3").exists()


def test_schema_validation_precedes_any_adapter_call(tmp_path, monkeypatch):
    invalid = manifest()
    invalid["changes"][0]["target"]["container_kind"] = "athlete_calendar"
    monkeypatch.setattr(pipeline, "create_read_registry",
                        lambda: (_ for _ in ()).throw(AssertionError("SHOULD_NOT_READ")))
    with pytest.raises(ChangeStop, match="TARGET_CONTAINER"):
        pipeline.unified_changeset_flow.fn(invalid, str(tmp_path/"ledger.sqlite3"))
    assert not (tmp_path/"ledger.sqlite3").exists()



def test_prefect_routes_one_manifest_through_vpc_read_transport(tmp_path, monkeypatch):
    selected = []
    def registry(transport):
        selected.append(transport)
        return {"plan.workout.patch": SyntheticReadAdapter()}
    monkeypatch.setattr(pipeline, "create_read_registry", registry)
    result = pipeline.unified_changeset_flow(
        manifest(), str(tmp_path/"vpc-ledger.sqlite3"),
        read_transport="private_bridge",
        requested_targets=[REQUESTED_TARGET],
    )
    assert selected == ["private_bridge"]
    assert result["mode"] == "preview"
    assert result["provider_writes"] == 0
    assert result["publication_enabled"] is False


def test_deployment_is_unscheduled_private_preview_only():
    from pathlib import Path
    import yaml
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] /
                          "prefect/ironman-unified-changeset-v1.yaml").read_text())
    dep = cfg["deployments"][0]
    assert dep["parameters"]["mode"] == "preview"
    assert dep["parameters"]["read_transport"] == "private_bridge"
    assert dep["schedules"] == []
    assert "readonly" in dep["tags"]


def test_missing_requested_targets_stops_before_ledger_or_provider(tmp_path, monkeypatch):
    def must_not_read(*args, **kwargs):
        raise AssertionError("PROVIDER_MUST_NOT_BE_CONTACTED")
    monkeypatch.setattr(pipeline, "create_read_registry", must_not_read)
    db = str(tmp_path / "missing-target.sqlite3")
    with pytest.raises(ChangeStop, match="REQUEST_TARGET_BINDING_REQUIRED"):
        pipeline.unified_changeset_flow.fn(manifest(), db)
    assert not Path(db).exists()


def test_stale_manifest_intermediate_does_not_select_current_winter_target(tmp_path, monkeypatch):
    def must_not_read(*args, **kwargs):
        raise AssertionError("PROVIDER_MUST_NOT_BE_CONTACTED")
    monkeypatch.setattr(pipeline, "create_read_registry", must_not_read)
    requested = {
        **REQUESTED_TARGET,
        "target": {**REQUESTED_TARGET["target"], "container_id": 689369}
    }
    db = str(tmp_path / "stale.sqlite3")
    with pytest.raises(ChangeStop, match="STOP_TARGET_MISMATCH"):
        pipeline.unified_changeset_flow.fn(
            manifest(), db, requested_targets=[requested])
    assert not Path(db).exists()


def test_exact_binding_rejects_extra_or_wrong_resource(tmp_path, monkeypatch):
    def must_not_read(*args, **kwargs):
        raise AssertionError("PROVIDER_MUST_NOT_BE_CONTACTED")
    monkeypatch.setattr(pipeline, "create_read_registry", must_not_read)
    expected = {"kind": REQUESTED_TARGET["kind"],
                "target": {**REQUESTED_TARGET["target"], "resource_id": 78}}
    db = str(tmp_path / "wrong-resource.sqlite3")
    for requested in ([expected], [REQUESTED_TARGET, expected],
                      [REQUESTED_TARGET, REQUESTED_TARGET]):
        with pytest.raises(ChangeStop, match="STOP_TARGET_MISMATCH|REQUEST_TARGET_BINDING_DUPLICATE"):
            pipeline.unified_changeset_flow.fn(
                manifest(), db, requested_targets=requested)
    assert not Path(db).exists()


def test_independent_requested_targets_work_for_any_plan_without_new_job(tmp_path, monkeypatch):
    calls = []
    class Provider:
        def read(self, item):
            calls.append(item["target"]["container_id"])
            return {"id": 77, "description": "old"}
        def apply(self, item):
            raise AssertionError("READ_ONLY_PREVIEW")
    monkeypatch.setattr(pipeline, "create_read_registry",
                        lambda read_transport="local": {"plan.workout.patch": Provider()})
    for plan_id in (684602, 689369):
        m = manifest()
        m["request_id"] = "universal-preview-" + str(plan_id)
        m["changes"][0]["target"]["container_id"] = plan_id
        approved = {
            **REQUESTED_TARGET,
            "target": {**REQUESTED_TARGET["target"], "container_id": plan_id}
        }
        result = pipeline.unified_changeset_flow(
            m, str(tmp_path / "multi-plan.sqlite3"),
            requested_targets=[approved])
        assert result["results"][0]["state"] == "PREFLIGHT_PASS"
        assert result["provider_writes"] == 0
    assert calls == [684602, 689369]
