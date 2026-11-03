"""Provider-free regression tests: no Google/TrainingPeaks writes."""
from scripts.ironman_jobs.operation_completion_gate import (
    assess_google_doc, assess_tp_publisher_report,
)


def docs(**overrides):
    args = dict(
        expected_document_id="doc-1",
        readback_document_id="doc-1",
        revision_id="revision-2",
        paragraphs=[{"text": "W01 bike 11 run 12"}, {"text": "W24 bike 47 run 48"},
                    {"text": "3 alleggerimenti compensativi"}],
        required_fragments=["W01 bike 11", "W24 bike 47",
                            "3 alleggerimenti compensativi"],
        readback_after_attempt=True,
    )
    args.update(overrides)
    return assess_google_doc(**args)


def tp(**overrides):
    report = dict(
        stage="PLAN_PATCH_PUBLISH_VERIFIED",
        plan=685173,
        manifest_sha256="manifest-digest",
        targets=48,
        provider_writes=0,
        readback_verified=True,
        athlete_calendar_writes=0,
        library_writes=0,
    )
    report.update(overrides.pop("report_updates", {}))
    args = dict(expected_plan_id=685173,
                expected_manifest_sha256="manifest-digest",
                expected_target_count=48, report=report)
    args.update(overrides)
    return assess_tp_publisher_report(**args)


def test_drive_real_readback_makes_checkpoint_verifiable():
    assert docs().state == "VERIFICATA"


def test_drive_existing_content_can_be_verified_without_claiming_writer():
    assert docs().reason == "CONTENUTO_PRESENTE_NEL_PROVIDER"


def test_drive_receipt_without_readback_must_not_claim_success():
    assert docs(readback_after_attempt=False).state == "NON_VERIFICATA"


def test_drive_revision_missing_must_not_claim_success():
    assert docs(revision_id=None).state == "NON_VERIFICATA"


def test_drive_wrong_document_id_must_not_claim_success():
    assert docs(readback_document_id="other").state == "NON_VERIFICATA"


def test_drive_partial_24_week_content_is_not_verified():
    result = docs(paragraphs=["W01 bike 11 run 12"])
    assert result.state == "NON_VERIFICATA"
    assert result.checked_items == 1


def test_drive_missing_required_fragments_fails_closed():
    assert docs(required_fragments=[]).state == "NON_VERIFICATA"


def test_drive_explicit_denial_must_not_be_retried_by_gate():
    result = docs(denied_by_security=True)
    assert result.state == "BLOCCATA"
    assert "NON_RIPETERE" in result.reason


def test_tp_only_verified_publish_report_is_accepted():
    assert tp().state == "VERIFICATA"


def test_tp_preview_is_not_a_completed_write():
    assert tp(report_updates={"stage": "PLAN_PATCH_PREVIEW_PASS"}).state == "NON_VERIFICATA"


def test_tp_wrong_plan_or_manifest_rejected():
    assert tp(report_updates={"plan": 686994}).state == "NON_VERIFICATA"
    assert tp(report_updates={"manifest_sha256": "other"}).state == "NON_VERIFICATA"


def test_tp_missing_readback_rejected():
    assert tp(report_updates={"readback_verified": False}).state == "NON_VERIFICATA"


def test_tp_unapproved_side_effect_rejected():
    assert tp(report_updates={"athlete_calendar_writes": 1}).state == "NON_VERIFICATA"


def test_tp_denial_is_not_turned_into_a_retry():
    assert tp(denied_by_security=True).state == "BLOCCATA"
