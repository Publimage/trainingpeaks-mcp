"""Synthetic transport and source fixtures; no secrets or private payloads."""
import asyncio
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from scripts.ironman_jobs.swim_audit_acquisition import (
    RECORD_SCHEMA, AcquisitionStop, acquire_swim_audit, extract_record,
)
from scripts.ironman_jobs.swim_audit_report import payload_sha256

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
TARGET = {"provider": "trainingpeaks", "owner_id": "200", "resource_kind": "library_template",
          "container_id": "300", "workout_id": "400"}


def fixtures():
    record = {"schema": RECORD_SCHEMA, "target": copy.deepcopy(TARGET), "recovery": {
        "schema": "IRONMAN_SWIM_RECOVERY_V1", "source_ref": "synthetic-doc",
        "coverage": "complete", "total_m": 300,
        "pauses": [{"after_m": 100, "seconds": 20}, {"after_m": 200, "seconds": 20}]}}
    request = {"target": copy.deepcopy(TARGET), "document_id": "synthetic-doc",
               "document_title": "Synthetic source", "section": "sample",
               "reviewed_record_sha256": payload_sha256(record), "validator_revision": "a" * 40}
    work = {"length": {"value": 100, "unit": "meter"}, "intensityClass": "active"}
    rest = {"length": {"value": 20, "unit": "second"}, "intensityClass": "rest",
            "targets": [{"minValue": 0, "maxValue": 0}]}
    item = {"exerciseLibraryId": 300, "exerciseLibraryItemId": 400,
            "exerciseLibraryItemType": "WorkoutTemplate", "workoutTypeId": 1,
            "distancePlanned": 300, "description": "Synthetic fixture",
            "structure": {"primaryLengthMetric": "distance", "structure": [
                {"type": "repetition", "length": {"value": 2, "unit": "repetition"},
                 "steps": [copy.deepcopy(work), rest]},
                {"type": "step", "length": {"value": 1, "unit": "repetition"}, "steps": [work]}]}}
    return request, record, item


def document(record):
    text = '[SWIM_AUDIT_BEGIN:sample]\n' + json.dumps(record) + '\n[SWIM_AUDIT_END:sample]'
    entry = {"document_id": "synthetic-doc", "title": "Synthetic source", "source": "GOOGLE_DRIVE",
             "version_kind": "DRIVE_FILE_VERSION", "source_version": "10",
             "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
             "retrieved_at_utc": NOW.isoformat()}
    return entry, text


class FakeDrive:
    def __init__(self, record):
        self.values = [document(record), document(record)]
        self.calls = []
        self.errors = []

    def read_document(self, spec):
        self.calls.append(spec)
        if self.errors:
            raise self.errors.pop(0)
        return copy.deepcopy(self.values[min(len(self.calls)-1, 1)])


class FakeTP:
    def __init__(self, item):
        self.items = [copy.deepcopy(item), copy.deepcopy(item)]
        self.owner = 200
        self.calls = []
        self.item_reads = 0
        self.error_response = False
        self.errors = []
        self.duplicate = False

    async def get(self, path):
        self.calls.append(path)
        if self.errors:
            raise self.errors.pop(0)
        if path == '/exerciselibrary/v2/libraries':
            data = [{"exerciseLibraryId": 300, "ownerId": self.owner}]
        else:
            assert path == '/exerciselibrary/v2/libraries/300/items'
            data = [copy.deepcopy(self.items[min(self.item_reads, 1)])]
            self.item_reads += 1
            if self.duplicate:
                data *= 2
        return SimpleNamespace(is_error=self.error_response, data=data)

    async def put(self, *args):
        raise AssertionError('A readonly audit must never write')


def run(request, drive, tp):
    return asyncio.run(acquire_swim_audit(request, drive_reader=drive, tp_client=tp,
                                        now_fn=lambda: NOW))


def test_end_to_end_adapter_calls_readers_twice_and_passes_narrow_scope():
    request, record, item = fixtures()
    drive, tp = FakeDrive(record), FakeTP(item)
    result = run(request, drive, tp)
    assert result['status'] == 'PASS'
    assert result['technical_checks_passed'] is True
    assert result['publishing_authorized'] is False
    assert result['external_authenticity_verified'] is False
    assert result['provider_writes'] == 0
    assert len(drive.calls) == 2 and len(tp.calls) == 4
    assert result['report']['source']['revision'] == 'DRIVE_FILE_VERSION:10'


def test_missing_pause_remains_fail_even_with_stable_authored_source():
    request, record, item = fixtures()
    item['structure']['structure'][0]['steps'].pop()
    result = run(request, FakeDrive(record), FakeTP(item))
    assert result['status'] == 'FAIL'
    assert result['report']['checks']['distance']['status'] == 'PASS'
    assert result['report']['checks']['recoveries']['status'] == 'FAIL'


def test_targeted_prescription_never_becomes_full_pass():
    request, record, item = fixtures()
    record['recovery']['coverage'] = 'targeted'
    request['reviewed_record_sha256'] = payload_sha256(record)
    assert run(request, FakeDrive(record), FakeTP(item))['status'] == 'PARTIAL'


@pytest.mark.parametrize('field,value,code', [
    ('source_version', '11', 'SOURCE_CHANGED_DURING_READ'),
    ('document_id', 'other', 'SOURCE_IDENTITY_MISMATCH'),
    ('title', 'other', 'SOURCE_IDENTITY_MISMATCH'),
    ('source_version', '', 'SOURCE_VERSION_MISSING'),
    ('version_kind', 'LOCAL_COPY', 'SOURCE_PROVIDER_OR_VERSION_KIND'),
    ('source', 'CHAT_MEMORY', 'SOURCE_PROVIDER_OR_VERSION_KIND'),
    ('content_sha256', '0'*64, 'SOURCE_CONTENT_HASH_MISMATCH'),
    ('retrieved_at_utc', (NOW-timedelta(seconds=301)).isoformat(), 'SOURCE_READ_NOT_FRESH'),
    ('retrieved_at_utc', (NOW+timedelta(seconds=1)).isoformat(), 'SOURCE_READ_NOT_FRESH'),
    ('retrieved_at_utc', 'not-a-date', 'SOURCE_TIMESTAMP_INVALID'),
])
def test_source_metadata_or_version_drift_blocks_success(field, value, code):
    request, record, item = fixtures()
    drive = FakeDrive(record)
    drive.values[1][0][field] = value
    result = run(request, drive, FakeTP(item))
    assert result['status'] == 'UNVERIFIABLE' and result['code'] == code
    assert result['technical_checks_passed'] is False
    assert 'report' not in result


def test_content_changed_without_version_change_is_detected():
    request, record, item = fixtures()
    drive = FakeDrive(record)
    entry, text = drive.values[1]
    text += '\nchanged'
    entry['content_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    drive.values[1] = entry, text
    assert run(request, drive, FakeTP(item))['code'] == 'SOURCE_CHANGED_DURING_READ'


@pytest.mark.parametrize('field,value', [('description', 'changed'), ('distancePlanned', 350)])
def test_provider_changed_during_read_invalidates_result(field, value):
    request, record, item = fixtures()
    tp = FakeTP(item)
    tp.items[1][field] = value
    assert run(request, FakeDrive(record), tp)['code'] == 'TP_CHANGED_DURING_READ'


@pytest.mark.parametrize('field,value,code', [
    ('exerciseLibraryId', 301, 'TP_CONTAINER_MISMATCH'),
    ('exerciseLibraryItemId', 401, 'TP_ITEM_NOT_UNIQUE'),
    ('workoutTypeId', 2, 'TP_NOT_SWIM_TEMPLATE'),
    ('exerciseLibraryItemType', 'NoteTemplate', 'TP_NOT_SWIM_TEMPLATE'),
])
def test_wrong_provider_resource_is_rejected(field, value, code):
    request, record, item = fixtures()
    item[field] = value
    assert run(request, FakeDrive(record), FakeTP(item))['code'] == code


def test_unreviewed_record_is_rejected_before_provider_read():
    request, record, item = fixtures()
    record['recovery']['pauses'][0]['seconds'] = 30
    tp = FakeTP(item)
    assert run(request, FakeDrive(record), tp)['code'] == 'SOURCE_RECORD_NOT_REVIEWED'
    assert not tp.calls


def test_source_target_mismatch_is_not_repaired_or_assumed():
    request, record, item = fixtures()
    record['target']['workout_id'] = '401'
    request['reviewed_record_sha256'] = payload_sha256(record)
    assert run(request, FakeDrive(record), FakeTP(item))['code'] == 'SOURCE_TARGET_MISMATCH'


def test_wrong_source_reference_is_rejected():
    request, record, item = fixtures()
    record['recovery']['source_ref'] = 'other-doc'
    request['reviewed_record_sha256'] = payload_sha256(record)
    assert run(request, FakeDrive(record), FakeTP(item))['code'] == 'SOURCE_RECOVERY_REFERENCE'


def test_wrong_owner_is_not_ignored():
    request, record, item = fixtures()
    tp = FakeTP(item)
    tp.owner = 999
    assert run(request, FakeDrive(record), tp)['code'] == 'TP_OWNER_MISMATCH'
    assert len(tp.calls) == 1


def test_provider_error_is_not_retried_blindly_or_reported_as_success():
    request, record, item = fixtures()
    tp = FakeTP(item)
    tp.error_response = True
    assert run(request, FakeDrive(record), tp)['code'] == 'TP_READ_FAILED'
    assert len(tp.calls) == 1


def test_duplicate_provider_item_is_ambiguous():
    request, record, item = fixtures()
    tp = FakeTP(item)
    tp.duplicate = True
    assert run(request, FakeDrive(record), tp)['code'] == 'TP_ITEM_NOT_UNIQUE'


@pytest.mark.parametrize('error', [PermissionError('private'), RuntimeError('secret-value')])
def test_permissions_and_unclassified_reader_rejection_are_not_retried_or_leaked(error):
    request, record, item = fixtures()
    drive = FakeDrive(record)
    drive.errors = [error]
    result = run(request, drive, FakeTP(item))
    assert result['status'] == 'UNVERIFIABLE'
    assert len(drive.calls) == 1
    assert str(error) not in json.dumps(result)


def test_transient_read_failure_is_recovered_without_writes():
    request, record, item = fixtures()
    tp = FakeTP(item)
    tp.errors = [TimeoutError(), ConnectionError()]
    result = run(request, FakeDrive(record), tp)
    assert result['status'] == 'PASS' and len(tp.calls) == 6


def test_transient_retries_are_bounded():
    request, record, item = fixtures()
    tp = FakeTP(item)
    tp.errors = [TimeoutError()] * 4
    assert run(request, FakeDrive(record), tp)['code'] == 'READ_TRANSPORT_UNAVAILABLE'
    assert len(tp.calls) == 3


def test_inputs_are_not_mutated():
    request, record, item = fixtures()
    originals = copy.deepcopy((request, record, item))
    run(request, FakeDrive(record), FakeTP(item))
    assert (request, record, item) == originals


@pytest.mark.parametrize('change', ['scope', 'hash', 'revision', 'id', 'extra'])
def test_bad_job_configuration_fails_before_reads(change):
    request, record, item = fixtures()
    if change == 'scope': request['target']['resource_kind'] = 'training_plan_workout'
    if change == 'hash': request['reviewed_record_sha256'] = ''
    if change == 'revision': request['validator_revision'] = 'main'
    if change == 'id': request['target']['container_id'] = '../300'
    if change == 'extra': request['unexpected'] = True
    drive, tp = FakeDrive(record), FakeTP(item)
    assert run(request, drive, tp)['status'] == 'UNVERIFIABLE'
    assert not drive.calls and not tp.calls


@pytest.mark.parametrize('text', ['', '{}', '[SWIM_AUDIT_BEGIN:sample]{}',
    '[SWIM_AUDIT_END:sample][SWIM_AUDIT_BEGIN:sample]',
    '[SWIM_AUDIT_BEGIN:sample]{"schema":1,"schema":2}[SWIM_AUDIT_END:sample]',
    '[SWIM_AUDIT_BEGIN:sample]{"bad":NaN}[SWIM_AUDIT_END:sample]'])
def test_no_guessing_missing_ambiguous_or_malformed_source_records(text):
    with pytest.raises(AcquisitionStop):
        extract_record(text, 'sample')
