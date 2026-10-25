"""No network, provider or Prefect imports required for operation drafts."""
import hashlib
import json
import os
import pytest
from scripts.ironman_jobs.ironman_dynamic_request_store import (
    DraftStop, DraftStore, KINDS, prepare_draft,
)


def h(text):
    return hashlib.sha256(text.encode()).hexdigest()


def item(kind, *, id="a01", container_kind="training_plan", container_id=501,
         resource_id=31, depends_on=None, payload=None):
    return {"id": id, "kind": kind,
            "target": {"provider": "trainingpeaks", "owner_id": 2116886,
                       "container_kind": container_kind, "container_id": container_id,
                       "resource_id": resource_id},
            "payload": payload if payload is not None else {"new_title": "New prescription"},
            "before_sha256": h(f"provider snapshot {id}"),
            "depends_on": depends_on or []}


def test_all_supported_operations_have_real_scope_and_no_whitelist():
    assert len(KINDS) >= 10
    for kind, (container, presence, readiness) in KINDS.items():
        draft = prepare_draft([item(kind, container_kind=container,
                                    container_id=None if presence == "new_container" else 987654321,
                                    resource_id=321 if presence == "existing_item" else None)])
        assert draft["state"] == "DRAFT_ONLY"
        assert draft["publication_authorized"] is False
        assert draft["provider_writes"] == 0
        assert draft["items"][0]["adapter_readiness"] == readiness
        assert draft["items"][0]["target"]["container_id"] == (
            None if presence == "new_container" else 987654321)


def test_multi_plan_batch_allows_independent_actions_but_disallows_wrong_owner():
    first = item("plan.workout.patch", id="w01", container_id=501, resource_id=31)
    other = item("plan.workout.patch", id="w02", container_id=902, resource_id=51)
    third = item("plan.note.attachment.add", id="pdf1", container_id=902,
                 resource_id=81, payload={"asset_ref": "sha256:abc", "name": "guide.pdf"})
    draft = prepare_draft([first, other, third])
    assert len(draft["items"]) == 3
    assert len({x["target"]["container_id"] for x in draft["items"]}) == 2
    other["target"]["owner_id"] = 123
    with pytest.raises(DraftStop, match="TARGET_MISMATCH"):
        prepare_draft([first, other])


def test_new_plan_is_not_assigned_an_old_resource_id():
    new = item("plan.create", container_id=None, resource_id=None)
    assert prepare_draft([new])["items"][0]["target"]["resource_id"] is None
    new["target"]["resource_id"] = 689369
    with pytest.raises(DraftStop, match="CREATE_REQUIRES_ABSENT_CONTAINER"):
        prepare_draft([new])


def test_existing_delete_requires_exact_ids_and_provider_snapshot():
    delete = item("athlete.workout.delete", container_kind="athlete_calendar",
                  container_id=22, resource_id=44)
    assert prepare_draft([delete])["items"][0]["target"]["container_id"] == 22
    delete["target"]["resource_id"] = None
    with pytest.raises(DraftStop, match="EXISTING_RESOURCE_ID_REQUIRED"):
        prepare_draft([delete])
    delete["target"]["resource_id"] = 44
    delete["before_sha256"] = "none"
    with pytest.raises(DraftStop, match="PROVIDER_SNAPSHOT_REQUIRED"):
        prepare_draft([delete])


def test_repeated_edits_are_explicitly_ordered_without_cross_plan_mixup():
    first = item("plan.workout.patch", id="one")
    second = item("plan.workout.patch", id="two")
    with pytest.raises(DraftStop, match="SHARED_RESOURCE_REQUIRES_DEPENDENCY"):
        prepare_draft([first, second])
    second["depends_on"] = ["one"]
    assert len(prepare_draft([first, second])["items"]) == 2
    first["depends_on"] = ["two"]
    with pytest.raises(DraftStop, match="DEPENDENCY_CYCLE"):
        prepare_draft([first, second])


@pytest.mark.parametrize("invalid", ["bad", ["x"], [True], ["x", "x"]])
def test_dependency_validation_never_crashes_on_unhashable_data(invalid):
    candidate = item("plan.workout.patch")
    candidate["depends_on"] = invalid
    with pytest.raises(DraftStop, match="DEPENDENCY_INVALID"):
        prepare_draft([candidate])


def test_payload_does_not_persist_bearer_cookie_or_signed_urls():
    for payload in ({"signed_url": "secret"}, {"nested": {"access_token": "token"}},
                    {"normal": "https://example.com/signed?token=123"},
                    {"x": "Bearer secret"}):
        with pytest.raises(DraftStop, match="SECRET_BEARING_FIELD|PAYLOAD_DIRECT_URL_OR_CREDENTIAL"):
            prepare_draft([item("plan.workout.patch", payload=payload)])


def test_cross_chat_retries_are_idempotent_and_db_is_private(tmp_path):
    candidate = item("plan.workout.patch")
    one = prepare_draft([candidate], request_key="one-user-instruction-2026")
    same = prepare_draft([candidate], request_key="one-user-instruction-2026")
    assert one == same
    file = tmp_path / "requests.sqlite3"
    store = DraftStore(file)
    try:
        assert store.store(one)["reused"] is False
        assert store.store(same)["reused"] is True
        assert store.get(one["request_id"]) == one
        assert store.get("ironman-missing") is None
        assert os.stat(file).st_mode & 0o077 == 0
        changed = item("plan.workout.patch", payload={"new_title": "Different"})
        conflicted = prepare_draft([changed], request_key="one-user-instruction-2026")
        with pytest.raises(DraftStop, match="REQUEST_ID_REUSED_DIFFERENT_PAYLOAD"):
            store.store(conflicted)
        assert store.get(one["request_id"]) == one
        tampered = dict(one, publication_authorized=True)
        with pytest.raises(DraftStop, match="DRAFT_NOT_READ_ONLY"):
            store.store(tampered)
    finally:
        store.close()


def test_semantic_fingerprint_is_independent_of_previously_used_plan():
    first = prepare_draft([item("plan.workout.patch", container_id=501)])
    second = prepare_draft([item("plan.workout.patch", container_id=902)])
    assert first["request_id"] != second["request_id"]
    assert first["semantic_sha256"] != second["semantic_sha256"]
    assert not any("684602" in json.dumps(x) or "689369" in json.dumps(x) for x in [first, second])


def test_nonfinite_numbers_are_not_stored():
    with pytest.raises(DraftStop, match="DRAFT_JSON_INVALID"):
        prepare_draft([item("plan.workout.patch", payload={"number": float("nan")})])
