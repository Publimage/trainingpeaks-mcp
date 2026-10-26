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


def test_compiles_multi_plan_changeset_preview_without_git_manifest():
    from scripts.ironman_jobs.ironman_dynamic_request_store import compile_preview_changeset
    first = item("plan.workout.patch", id="w01", container_id=501, resource_id=31)
    second = item("plan.workout.patch", id="w02", container_id=902, resource_id=51)
    draft = prepare_draft([first, second])
    bundle = compile_preview_changeset(draft, {"w01": {"title": "Revised A"},
                                                 "w02": {"title": "Revised B"}},
                                        pinned_revision="a" * 40)
    manifest = bundle["manifest"]
    assert manifest["schema"] == "IRONMAN_CHANGESET_V1"
    assert manifest["request_id"] == draft["request_id"]
    assert manifest["approval_scope"].startswith("PREVIEW_ONLY:")
    assert {x["target"]["container_id"] for x in manifest["changes"]} == {501, 902}
    assert bundle["publication_authorized"] is False
    assert bundle["provider_writes"] == 0


def test_unverified_create_and_delete_never_compile_into_writer_preview():
    from scripts.ironman_jobs.ironman_dynamic_request_store import compile_preview_changeset
    for kind, container_id, resource_id in (("plan.create", None, None),
                                            ("plan.workout.delete", 501, 31),
                                            ("athlete.workout.delete", 25, 31)):
        container = "athlete_calendar" if kind.startswith("athlete.") else "training_plan"
        draft = prepare_draft([item(kind, container_kind=container,
                                    container_id=container_id, resource_id=resource_id)])
        with pytest.raises(DraftStop, match="PREVIEW_ADAPTER_NOT_RELEASED"):
            compile_preview_changeset(draft, {"a01": {"before": "not passed"}},
                                      pinned_revision="a" * 40)


def test_compiler_rejects_missing_after_images_and_bad_revision():
    from scripts.ironman_jobs.ironman_dynamic_request_store import compile_preview_changeset
    draft = prepare_draft([item("plan.workout.patch")])
    with pytest.raises(DraftStop, match="PREVIEW_AFTER_IMAGES_INCOMPLETE"):
        compile_preview_changeset(draft, {}, pinned_revision="a"*40)
    with pytest.raises(DraftStop, match="PINNED_REVISION_REQUIRED"):
        compile_preview_changeset(draft, {"a01": {"title": "x"}}, pinned_revision="current")


def test_one_request_creates_plan_then_workouts_and_native_note_with_pdf():
    new_plan = item("plan.create", id="create-plan", container_id=None,
                    resource_id=None, payload={"title": "New 2027 plan"})
    workout_1 = item("plan.workout.create", id="run01", container_id=None,
                     resource_id=None, depends_on=["create-plan"],
                     payload={"title": "Easy run"})
    workout_1["target"]["container_ref"] = "create-plan"
    workout_2 = item("plan.workout.create", id="swim01", container_id=None,
                     resource_id=None, depends_on=["create-plan"],
                     payload={"title": "Swim technique"})
    workout_2["target"]["container_ref"] = "create-plan"
    new_note = item("plan.note.create", id="note01", container_id=None,
                    resource_id=None, depends_on=["create-plan"],
                    payload={"title": "First week instructions"})
    new_note["target"]["container_ref"] = "create-plan"
    pdf = item("plan.note.attachment.add", id="pdf01", container_id=None,
               resource_id=None, depends_on=["create-plan", "note01"],
               payload={"filename": "instructions.pdf", "sha256": h("pdf bytes")})
    pdf["target"].update({"container_ref": "create-plan", "resource_ref": "note01"})
    draft = prepare_draft([new_plan, workout_1, workout_2, new_note, pdf])
    assert len(draft["items"]) == 5
    assert all(i["target"]["container_id"] is None for i in draft["items"])
    assert all(i["target"]["resource_id"] is None for i in draft["items"])
    assert draft["items"][-1]["target"]["resource_ref"] == "note01"
    assert draft["items"][-1]["adapter_readiness"] == "PROVEN_SCOPED"
    assert draft["provider_writes"] == 0


def test_plan_copy_can_be_parent_for_new_session():
    duplicate = item("plan.copy", id="copy-plan", container_id=501,
                     resource_id=None, payload={"title": "Independent copy"})
    session = item("plan.workout.create", id="run001", container_id=None,
                   resource_id=None, depends_on=["copy-plan"])
    session["target"]["container_ref"] = "copy-plan"
    assert prepare_draft([duplicate, session])["items"][1]["target"]["container_ref"] == "copy-plan"


def test_child_must_explicitly_depend_on_exact_plan_creator():
    new_plan = item("plan.create", id="new-plan", container_id=None, resource_id=None)
    child = item("plan.workout.create", id="new-workout", container_id=None,
                 resource_id=None)
    child["target"]["container_ref"] = "new-plan"
    with pytest.raises(DraftStop, match="CONTAINER_REF_MUST_DEPEND_ON_PLAN_CREATE_OR_COPY"):
        prepare_draft([new_plan, child])
    child["depends_on"] = ["new-plan"]
    child["target"]["container_ref"] = "nonexistent"
    with pytest.raises(DraftStop, match="CONTAINER_REF_MUST_DEPEND_ON_PLAN_CREATE_OR_COPY"):
        prepare_draft([new_plan, child])
    child["target"]["container_ref"] = "new-plan"
    assert prepare_draft([new_plan, child])["items"][1]["target"]["container_ref"] == "new-plan"


def test_new_pdf_note_must_match_type_parent_plan_and_dependency():
    new_note = item("plan.note.create", id="note001", container_id=501, resource_id=None)
    attachment = item("plan.note.attachment.add", id="pdf001", container_id=501,
                      resource_id=None, depends_on=["note001"])
    attachment["target"]["resource_ref"] = "note001"
    assert prepare_draft([new_note, attachment])["items"][1]["target"]["resource_ref"] == "note001"
    attachment["target"]["container_id"] = 902
    with pytest.raises(DraftStop, match="RESOURCE_REF_MUST_MATCH_PARENT_CREATOR"):
        prepare_draft([new_note, attachment])
    attachment["target"]["container_id"] = 501
    attachment["depends_on"] = []
    with pytest.raises(DraftStop, match="RESOURCE_REF_MUST_MATCH_PARENT_CREATOR"):
        prepare_draft([new_note, attachment])
    attachment["depends_on"] = ["note001"]
    new_note["kind"] = "plan.workout.create"
    with pytest.raises(DraftStop, match="RESOURCE_REF_MUST_MATCH_PARENT_CREATOR"):
        prepare_draft([new_note, attachment])


def test_symbolic_resource_id_never_reuses_a_positive_workout_id():
    create = item("plan.workout.create", id="create-001", container_id=501,
                  resource_id=None)
    patch = item("plan.workout.patch", id="patch-001", container_id=501,
                 resource_id=None, depends_on=["create-001"])
    patch["target"]["resource_ref"] = "create-001"
    assert prepare_draft([create, patch])["items"][1]["target"]["resource_id"] is None
    patch["target"]["resource_id"] = 689369
    with pytest.raises(DraftStop, match="EXISTING_RESOURCE_ID_REQUIRED"):
        prepare_draft([create, patch])


def test_plan_note_patch_is_consistent_between_draft_and_preview_schema():
    from scripts.ironman_jobs.ironman_dynamic_request_store import compile_preview_changeset
    note = item("plan.note.patch", container_id=6123, resource_id=9811)
    draft = prepare_draft([note])
    preview = compile_preview_changeset(draft, {"a01": {"title": "Updated note"}},
                                        pinned_revision="f" * 40)
    assert preview["manifest"]["changes"][0]["kind"] == "plan.note.patch"
    assert preview["state"] == "PREVIEW_ONLY"


def test_created_child_cannot_be_misrepresented_as_existing_preview_item():
    from scripts.ironman_jobs.ironman_dynamic_request_store import compile_preview_changeset
    new_note = item("plan.note.create", id="note1", container_id=501, resource_id=None)
    pdf = item("plan.note.attachment.add", id="pdf1", container_id=501,
               resource_id=None, depends_on=["note1"])
    pdf["target"]["resource_ref"] = "note1"
    draft = prepare_draft([new_note, pdf])
    with pytest.raises(DraftStop, match="PREVIEW_ADAPTER_NOT_RELEASED"):
        compile_preview_changeset(draft, {"note1": {}, "pdf1": {}},
                                  pinned_revision="a" * 40)


def test_symbolic_repeat_patches_need_direct_dependency():
    create = item("plan.workout.create", id="create01", container_id=501, resource_id=None)
    a = item("plan.workout.patch", id="patch01", container_id=501,
             resource_id=None, depends_on=["create01"])
    b = item("plan.workout.patch", id="patch02", container_id=501,
             resource_id=None, depends_on=["create01"])
    a["target"]["resource_ref"] = "create01"
    b["target"]["resource_ref"] = "create01"
    with pytest.raises(DraftStop, match="SHARED_RESOURCE_REQUIRES_DEPENDENCY"):
        prepare_draft([create, a, b])
    b["depends_on"] = ["create01", "patch01"]
    assert len(prepare_draft([create, a, b])["items"]) == 3


def test_forged_preview_draft_cannot_change_a_target_without_resubmission():
    from scripts.ironman_jobs.ironman_dynamic_request_store import compile_preview_changeset
    draft = prepare_draft([item("plan.workout.patch", container_id=501)])
    draft["items"][0]["target"]["container_id"] = 902
    with pytest.raises(DraftStop, match="DRAFT_TAMPERED"):
        compile_preview_changeset(draft, {"a01": {"title": "some change"}},
                                  pinned_revision="a"*40)


def test_persisted_db_draft_rejects_tampering_on_get(tmp_path):
    from scripts.ironman_jobs.ironman_dynamic_request_store import canonical
    draft = prepare_draft([item("plan.workout.patch", container_id=501)])
    db = DraftStore(tmp_path/"drafts.sqlite3")
    try:
        db.store(draft)
        altered = json.loads(canonical(draft))
        altered["items"][0]["target"]["container_id"] = 902
        db.db.execute("UPDATE drafts SET payload=? WHERE request_id=?",
                      (canonical(altered), draft["request_id"]))
        db.db.commit()
        with pytest.raises(DraftStop, match="DRAFT_TAMPERED"):
            db.get(draft["request_id"])
    finally:
        db.close()


def test_unmodified_draft_reads_and_compiles_with_integrity_check(tmp_path):
    from scripts.ironman_jobs.ironman_dynamic_request_store import compile_preview_changeset
    draft = prepare_draft([item("plan.note.patch", container_id=501, resource_id=19)])
    db = DraftStore(tmp_path/"drafts.sqlite3")
    try:
        db.store(draft)
        retrieved = db.get(draft["request_id"])
    finally:
        db.close()
    bundle = compile_preview_changeset(retrieved, {"a01": {"title": "changed"}},
                                       pinned_revision="a"*40)
    assert bundle["state"] == "PREVIEW_ONLY"
    assert bundle["provider_writes"] == 0


def test_optional_null_symbolic_keys_never_escape_into_changeset_v1():
    from scripts.ironman_jobs.ironman_dynamic_request_store import compile_preview_changeset
    current = item("plan.workout.patch", container_id=501, resource_id=31)
    current["target"]["container_ref"] = None
    current["target"]["resource_ref"] = None
    draft = prepare_draft([current])
    x = compile_preview_changeset(draft, {"a01": {"title": "Changed"}},
                                  pinned_revision="a" * 40)
    target = x["manifest"]["changes"][0]["target"]
    assert set(target) == {"provider", "owner_id", "container_kind",
                           "container_id", "resource_id"}
    assert target["container_id"] == 501 and target["resource_id"] == 31


def test_preview_must_match_actual_desired_payload_when_provided():
    from scripts.ironman_jobs.ironman_dynamic_request_store import compile_preview_changeset
    current = item("plan.workout.patch", container_id=501, resource_id=31,
                   payload={"desired": {"title": "Correct"}, "fields": ["title"]})
    draft = prepare_draft([current])
    with pytest.raises(DraftStop, match="PREVIEW_PAYLOAD_AFTER_IMAGE_MISMATCH"):
        compile_preview_changeset(draft, {"a01": {"title": "Different"}},
                                  pinned_revision="a" * 40)
    safe = compile_preview_changeset(draft, {"a01": {"title": "Correct"}},
                                    pinned_revision="a" * 40)
    assert safe["manifest"]["changes"][0]["payload"]["desired"] == {"title": "Correct"}



def _durable_preview_fixture(tmp_path):
    from scripts.ironman_jobs.ironman_dynamic_request_store import (
        compile_preview_changeset,
    )
    from scripts.ironman_jobs.ironman_unified_changeset_engine import digest
    desired = {"id": 31, "title": "new prescription"}
    raw = item("plan.workout.patch", payload={"desired": desired})
    draft = prepare_draft([raw], request_key="durable-preview-test-v1")
    compiled = compile_preview_changeset(
        draft, {"a01": desired}, pinned_revision="a" * 40,
    )
    m = compiled["manifest"]
    result = {
        "schema": "IRONMAN_CHANGESET_RESULT_V1",
        "request_id": draft["request_id"],
        "manifest_sha256": digest(m),
        "mode": "preview",
        "request_state": "PREVIEW_ONLY",
        "provider_writes_claimed": 0,
        "provider_writes": 0,
        "publication_enabled": False,
        "results": [{"id": "a01", "state": "PREFLIGHT_PASS"}],
    }
    return draft, m, result


def test_durable_previews_multiple_revisions_one_immutable_request(tmp_path):
    from scripts.ironman_jobs.ironman_dynamic_request_store import (
        compile_preview_changeset,
    )
    from scripts.ironman_jobs.ironman_unified_changeset_engine import digest
    draft, m1, r1 = _durable_preview_fixture(tmp_path)
    db = tmp_path / "request-store.sqlite3"
    store = DraftStore(db)
    try:
        store.store(draft)
        first = store.store_preview(m1, r1)
        assert first["state"] == "PREVIEW_ONLY"
        assert first["publication_authorized"] is False
        assert first["reused"] is False
        assert store.store_preview(m1, r1)["reused"] is True
        changed = {"id": 31, "title": "revised prescription"}
        m2 = compile_preview_changeset(
            prepare_draft([item("plan.workout.patch", payload={"desired": changed})],
                          request_key=draft["request_key"]),
            {"a01": changed}, pinned_revision="a" * 40,
        )["manifest"]
        # The immutable request cannot change: a revised preview must keep the
        # draft payload but may include a new independently reviewed after-image.
        # Therefore produce a different observation for the same manifest instead.
        r2 = {**r1, "results": [{"id": "a01", "state": "DONE_VERIFIED"}]}
        second = store.store_preview(m1, r2)
        assert second["preview_sha256"] != first["preview_sha256"]
        assert store.get_preview(draft["request_id"], second["preview_sha256"])["receipt"]["results"][0]["state"] == "DONE_VERIFIED"
    finally:
        store.close()
    reopened = DraftStore(db)
    try:
        assert reopened.get_preview(draft["request_id"], first["preview_sha256"])["manifest"] == m1
    finally:
        reopened.close()


@pytest.mark.parametrize("field,wrong", [
    ("request_state", "WORK_COMPLETE"),
    ("provider_writes_claimed", 1),
    ("publication_enabled", True),
    ("manifest_sha256", "f" * 64),
])
def test_durable_preview_rejects_non_read_only_receipts(tmp_path, field, wrong):
    draft, manifest, receipt = _durable_preview_fixture(tmp_path)
    store = DraftStore(tmp_path / "draft.sqlite3")
    try:
        store.store(draft)
        receipt[field] = wrong
        with pytest.raises(DraftStop, match="PREVIEW_RECEIPT_NOT_READ_ONLY"):
            store.store_preview(manifest, receipt)
    finally:
        store.close()


def test_durable_preview_refuses_failure_or_foreign_request(tmp_path):
    draft, manifest, receipt = _durable_preview_fixture(tmp_path)
    store = DraftStore(tmp_path / "draft.sqlite3")
    try:
        with pytest.raises(DraftStop, match="DRAFT_REQUEST_NOT_FOUND"):
            store.store_preview(manifest, receipt)
        store.store(draft)
        receipt["results"][0]["state"] = "BLOCKED_CONFLICT"
        with pytest.raises(DraftStop, match="PREVIEW_NOT_PASSED"):
            store.store_preview(manifest, receipt)
    finally:
        store.close()
