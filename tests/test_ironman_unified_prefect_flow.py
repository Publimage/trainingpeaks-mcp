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


def test_prepare_mode_stores_one_draft_for_new_chat_without_provider_calls(tmp_path, monkeypatch):
    from scripts.ironman_jobs.ironman_dynamic_request_store import DraftStore
    def no_provider(*args, **kwargs):
        raise AssertionError("PREPARE_MODE_MUST_NOT_READ_TP_OR_PREFECT_BRIDGE")
    monkeypatch.setattr(pipeline, "create_read_registry", no_provider)
    dest = tmp_path / "dynamic-requests.sqlite3"
    monkeypatch.setenv("IRONMAN_OPERATION_DRAFT_STORE", str(dest))
    user_input = {
        "schema": "IRONMAN_OPERATION_INPUT_V1",
        "request_key": "new-chat-on-a-new-plan-001",
        "items": [{
            "id": "new001", "kind": "plan.create",
            "target": {"provider": "trainingpeaks", "owner_id": 2116886,
                       "container_kind": "training_plan",
                       "container_id": None, "resource_id": None},
            "before_sha256": digest({"coach_owned_plans": "provider_inventory_sha"}),
            "depends_on": [], "payload": {"title": "Brand new plan"},
        }],
    }
    ledger = tmp_path / "unused-ledger.sqlite3"
    first = pipeline.unified_changeset_flow.fn(user_input, str(ledger), mode="prepare")
    assert first["state"] == "DRAFT_ONLY"
    assert first["reused"] is False
    assert first["provider_writes"] == 0
    assert first["publication_enabled"] is False
    assert first["adapter_readiness"]["new001"] == "UNVERIFIED_WRITER"
    second = pipeline.unified_changeset_flow.fn(user_input, str(ledger), mode="prepare")
    assert second["request_id"] == first["request_id"]
    assert second["reused"] is True
    assert not ledger.exists()
    store = DraftStore(dest)
    try:
        assert store.get(first["request_id"])["items"][0]["target"]["resource_id"] is None
    finally:
        store.close()


def test_prepare_mode_without_admin_store_config_never_touches_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("IRONMAN_OPERATION_DRAFT_STORE", raising=False)
    with pytest.raises(ChangeStop, match="DRAFT_STORE_NOT_CONFIGURED"):
        pipeline.unified_changeset_flow.fn(
            {"schema": "IRONMAN_OPERATION_INPUT_V1", "items": []},
            str(tmp_path / "not-created.sqlite3"), mode="prepare")
    assert not (tmp_path / "not-created.sqlite3").exists()



def test_multiple_previews_of_same_request_keep_execution_ledger_clean(tmp_path, monkeypatch):
    """Preview revisions never register the execution request_id in durable SQLite."""
    monkeypatch.setattr(
        pipeline, "create_read_registry",
        lambda read_transport="local": {"plan.workout.patch": SyntheticReadAdapter()},
    )
    ledger = tmp_path / "execution.sqlite3"
    first = manifest()
    result_a = pipeline.unified_changeset_flow.fn(
        first, str(ledger), mode="preview", requested_targets=[REQUESTED_TARGET],
    )
    second = manifest()
    second["changes"][0]["payload"]["desired"] = {
        "id": 77, "description": "new revision",
    }
    second["changes"][0]["after_sha256"] = digest(
        second["changes"][0]["payload"]["desired"],
    )
    second["approval_scope"] = "offline:preview:changed-revision"
    result_b = pipeline.unified_changeset_flow.fn(
        second, str(ledger), mode="preview", requested_targets=[REQUESTED_TARGET],
    )
    assert result_a["results"][0]["state"] == "PREFLIGHT_PASS"
    assert result_b["results"][0]["state"] == "PREFLIGHT_PASS"
    assert result_a["provider_writes"] == result_b["provider_writes"] == 0
    assert not ledger.exists()


def test_preview_same_request_does_not_touch_preexisting_execution_ledger(tmp_path, monkeypatch):
    """An execution ledger made by another process must not change on preview."""
    import sqlite3
    ledger = tmp_path / "execution.sqlite3"
    with sqlite3.connect(ledger) as connection:
        connection.execute("CREATE TABLE sentinel (item TEXT NOT NULL)")
        connection.execute("INSERT INTO sentinel VALUES ('untouched')")
    before = ledger.read_bytes()
    monkeypatch.setattr(
        pipeline, "create_read_registry",
        lambda read_transport="local": {"plan.workout.patch": SyntheticReadAdapter()},
    )
    result = pipeline.unified_changeset_flow.fn(
        manifest(), str(ledger), mode="preview", requested_targets=[REQUESTED_TARGET],
    )
    assert result["results"][0]["state"] == "PREFLIGHT_PASS"
    assert ledger.read_bytes() == before
    with sqlite3.connect(ledger) as connection:
        assert connection.execute("SELECT item FROM sentinel").fetchone() == ("untouched",)



def test_real_sqlite_engine_crosschat_preview_roundtrip(tmp_path, monkeypatch):
    """Real DraftStore + real Changeset Ledger + one Prefect flow, no TP writes."""
    from scripts.ironman_jobs.ironman_dynamic_request_store import DraftStore

    old = {"id": 77, "description": "old"}
    desired = {"id": 77, "description": "revised in later chat"}
    provider_reads = []
    provider_writes = []

    class ReadOnlyProvider:
        def read(self, spec):
            provider_reads.append(spec["target"]["container_id"])
            return dict(old)

        def apply(self, spec):
            provider_writes.append(spec["id"])
            raise AssertionError("UNAPPROVED_PROVIDER_MUTATION")

    monkeypatch.setattr(
        pipeline, "create_read_registry",
        lambda read_transport="local": {"plan.workout.patch": ReadOnlyProvider()},
    )
    db = tmp_path / "durable-requests.sqlite3"
    ledger = tmp_path / "durable-execution.sqlite3"
    monkeypatch.setenv("IRONMAN_OPERATION_DRAFT_STORE", str(db))
    target = dict(REQUESTED_TARGET["target"])
    prepared = pipeline.unified_changeset_flow.fn(
        {
            "schema": "IRONMAN_OPERATION_INPUT_V1",
            "request_key": "real-sqlite-crosschat-20261026",
            "items": [{
                "id": "change1",
                "kind": "plan.workout.patch",
                "target": target,
                "payload": {"desired": desired},
                "before_sha256": digest(old),
                "depends_on": [],
            }],
        },
        str(ledger),
        mode="prepare",
    )
    request_id = prepared["request_id"]
    assert prepared["state"] == "DRAFT_ONLY"
    assert prepared["provider_writes"] == 0
    assert not provider_reads and not provider_writes
    assert not ledger.exists()

    preview_input = {
        "schema": "IRONMAN_DRAFT_PREVIEW_INPUT_V1",
        "request_id": request_id,
        "after_images": {"change1": desired},
        "pinned_revision": "a" * 40,
    }
    first = pipeline.unified_changeset_flow.fn(
        preview_input, str(ledger), mode="preview_draft",
        requested_targets=[REQUESTED_TARGET],
    )
    assert first["preview_persisted"] is True
    assert first["results"][0]["state"] == "PREFLIGHT_PASS"
    assert first["provider_writes"] == 0
    assert provider_reads == [target["container_id"]]
    assert not provider_writes
    assert not ledger.exists()

    second = pipeline.unified_changeset_flow.fn(
        preview_input, str(ledger), mode="preview_draft",
        requested_targets=[REQUESTED_TARGET],
    )
    assert second["preview_sha256"] == first["preview_sha256"]
    assert second["preview_reused"] is True
    assert not ledger.exists()

    # Open SQLite from a separate connection, as a subsequent chat would do.
    reopened = DraftStore(db)
    try:
        saved = reopened.get_preview(request_id, first["preview_sha256"])
    finally:
        reopened.close()
    assert saved["manifest"]["request_id"] == request_id
    assert saved["publication_authorized"] is False

    reads_before_resume = list(provider_reads)
    resumed = pipeline.unified_changeset_flow.fn(
        {
            "schema": "IRONMAN_PREVIEW_RESUME_INPUT_V1",
            "request_id": request_id,
            "preview_sha256": first["preview_sha256"],
        },
        str(ledger), mode="resume_preview",
        requested_targets=[REQUESTED_TARGET],
    )
    assert resumed["results"][0]["state"] == "PREFLIGHT_PASS"
    assert resumed["source"] == "stored_read_only_preview"
    assert resumed["publication_enabled"] is False
    assert resumed["provider_writes"] == 0
    assert provider_reads == reads_before_resume
    assert not provider_writes
    assert not ledger.exists()

    wrong = [{
        "kind": "plan.workout.patch",
        "target": {**target, "container_id": 999999},
    }]
    with pytest.raises(ChangeStop, match="STOP_TARGET_MISMATCH"):
        pipeline.unified_changeset_flow.fn(
            {
                "schema": "IRONMAN_PREVIEW_RESUME_INPUT_V1",
                "request_id": request_id,
                "preview_sha256": first["preview_sha256"],
            },
            str(ledger), mode="resume_preview",
            requested_targets=wrong,
        )
    assert provider_reads == reads_before_resume
    assert not provider_writes
