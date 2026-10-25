"""Run the exact GitHub flow source without Prefect/cloud/provider installed."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest
from scripts.ironman_jobs.ironman_dynamic_request_store import DraftStore

PATH = Path(__file__).parents[1] / 'scripts/ironman_jobs/ironman_unified_prefect_flow.py'


@pytest.fixture
def flowhost(monkeypatch):
    calls = []
    fake_prefect = types.ModuleType('prefect')
    def decorator(**kwargs):
        def wrap(func):
            class FakeCall:
                fn = staticmethod(func)
                name = kwargs.get('name')
                def __call__(self, *args, **kwargs):
                    return func(*args, **kwargs)
            return FakeCall()
        return wrap
    fake_prefect.flow = decorator
    fake_prefect.task = decorator

    engine = types.ModuleType('scripts.ironman_jobs.ironman_unified_changeset_engine')
    class ChangeStop(Exception):
        pass
    class Ledger:
        def __init__(self, path):
            calls.append('LEDGER_OPEN')
        def close(self):
            calls.append('LEDGER_CLOSE')
    def validate_manifest(value):
        calls.append('CHANGESET_VALIDATION')
        return 'validated'
    def run_changeset(*args, **kwargs):
        calls.append('PREVIEW_PROVIDER')
        return {'mode': 'preview', 'results': []}
    engine.ChangeStop = ChangeStop
    engine.Ledger = Ledger
    engine.validate_manifest = validate_manifest
    engine.run_changeset = run_changeset
    reads = types.ModuleType('scripts.ironman_jobs.ironman_unified_trainingpeaks_reads')
    def create_read_registry(*args, **kwargs):
        calls.append('REMOTE_READER')
        return {}
    reads.create_read_registry = create_read_registry
    for name, module in (
        ('prefect', fake_prefect),
        ('scripts.ironman_jobs.ironman_unified_changeset_engine', engine),
        ('scripts.ironman_jobs.ironman_unified_trainingpeaks_reads', reads),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location('scripts.ironman_jobs.ironman_unified_prefect_flow', PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, 'scripts.ironman_jobs.ironman_unified_prefect_flow', module)
    spec.loader.exec_module(module)
    return module, calls, ChangeStop


def item(kind, id, *, container_id=None, resource_id=None, depends=None, target_extra=None):
    target = {'provider': 'trainingpeaks', 'owner_id': 2116886, 'container_kind': 'training_plan',
              'container_id': container_id, 'resource_id': resource_id}
    target.update(target_extra or {})
    return {'id': id, 'kind': kind, 'target': target, 'depends_on': depends or [],
            'before_sha256': 'a'*64, 'payload': {'title': kind + id}}


def request():
    return {'schema': 'IRONMAN_OPERATION_INPUT_V1', 'request_key': 'new-chat-plan-2027', 'items': [
        item('plan.create', 'newplan'),
        item('plan.workout.create', 'newrun', depends=['newplan'],
             target_extra={'container_ref': 'newplan'}),
        item('plan.note.create', 'newnote', depends=['newplan'],
             target_extra={'container_ref': 'newplan'}),
        item('plan.note.attachment.add', 'attachpdf', depends=['newplan', 'newnote'],
             target_extra={'container_ref': 'newplan', 'resource_ref': 'newnote'}),
    ]}


def test_e2e_prepare_same_request_creates_no_provider_activity(tmp_path, monkeypatch, flowhost):
    module, calls, _ = flowhost
    path = tmp_path/'drafts.sqlite3'
    monkeypatch.setenv('IRONMAN_OPERATION_DRAFT_STORE', str(path))
    first = module.unified_changeset_flow.fn(request(), str(tmp_path/'ledger.sqlite3'), mode='prepare')
    assert first['state'] == 'DRAFT_ONLY'
    assert first['publication_enabled'] is False
    assert first['adapter_readiness']['newrun'] == 'UNVERIFIED_WRITER'
    assert first['provider_writes'] == 0
    assert first['reused'] is False
    assert not calls
    second = module.unified_changeset_flow.fn(request(), str(tmp_path/'ledger.sqlite3'), mode='prepare')
    assert second['reused'] is True
    assert second['request_id'] == first['request_id']
    store = DraftStore(path)
    try:
        saved = store.get(first['request_id'])
    finally:
        store.close()
    assert saved['items'][-1]['target']['resource_ref'] == 'newnote'
    assert saved['items'][1]['target']['container_ref'] == 'newplan'
    assert saved['provider_writes'] == 0
    assert not (tmp_path/'ledger.sqlite3').exists()
    assert not calls


def test_reused_request_key_with_another_target_stops(tmp_path, monkeypatch, flowhost):
    module, calls, _ = flowhost
    path = tmp_path/'drafts.sqlite3'
    monkeypatch.setenv('IRONMAN_OPERATION_DRAFT_STORE', str(path))
    initial = request()
    module.unified_changeset_flow.fn(initial, 'unused', mode='prepare')
    new = request()
    new['items'][1]['payload']['title'] = 'changed intended workout'
    with pytest.raises(Exception, match='REQUEST_ID_REUSED_DIFFERENT_PAYLOAD'):
        module.unified_changeset_flow.fn(new, 'unused', mode='prepare')
    assert not calls


def test_publish_remains_rejected_before_any_writes(tmp_path, monkeypatch, flowhost):
    module, calls, ChangeStop = flowhost
    monkeypatch.setenv('IRONMAN_OPERATION_DRAFT_STORE', str(tmp_path/'no.sqlite3'))
    with pytest.raises(ChangeStop, match='PUBLISHING_NOT_YET_ENABLED'):
        module.unified_changeset_flow.fn(request(), 'unused', mode='publish')
    assert not (tmp_path/'no.sqlite3').exists()
    assert not calls


def test_unapproved_target_preflight_never_opens_ledger(tmp_path, monkeypatch, flowhost):
    module, calls, ChangeStop = flowhost
    changeset = {'owner_id': 2116886, 'changes': [
        {'id': 'patch01', 'kind': 'plan.workout.patch', 'target': {
            'provider':'trainingpeaks', 'owner_id': 2116886, 'container_kind':'training_plan',
            'container_id': 501, 'resource_id': 31}}]}
    with pytest.raises(ChangeStop, match='REQUEST_TARGET_BINDING_REQUIRED'):
        module.unified_changeset_flow.fn(changeset, str(tmp_path/'no-ledger.db'), mode='preview')
    assert calls == ['CHANGESET_VALIDATION']
    assert not (tmp_path/'no-ledger.db').exists()


def test_prepared_existing_item_can_be_previewed_from_store_without_new_manifest(tmp_path, monkeypatch, flowhost):
    module, calls, _ = flowhost
    path = tmp_path / 'drafts.sqlite3'
    monkeypatch.setenv('IRONMAN_OPERATION_DRAFT_STORE', str(path))
    request = {'schema': 'IRONMAN_OPERATION_INPUT_V1', 'request_key': 'patch-in-one-chat',
               'items': [item('plan.workout.patch', 'patch01', container_id=501,
                              resource_id=31)]}
    stored = module.unified_changeset_flow.fn(request, 'unused', mode='prepare')
    preview_input = {'schema':'IRONMAN_DRAFT_PREVIEW_INPUT_V1',
                     'request_id':stored['request_id'],
                     'after_images':{'patch01':{'title':'updated run'}},
                     'pinned_revision':'f'*40}
    requested_targets = [{'kind':'plan.workout.patch', 'target':{
        'provider':'trainingpeaks','owner_id':2116886,
        'container_kind':'training_plan','container_id':501,'resource_id':31}}]
    result = module.unified_changeset_flow.fn(preview_input, str(tmp_path/'ledger.sqlite3'),
                                               mode='preview_draft', requested_targets=requested_targets)
    assert result['request_id'] == stored['request_id']
    assert result['provider_writes'] == 0
    assert result['publication_enabled'] is False
    assert result['approval_scope'].startswith('PREVIEW_ONLY:')
    assert calls == ['CHANGESET_VALIDATION', 'LEDGER_OPEN', 'REMOTE_READER',
                     'PREVIEW_PROVIDER', 'LEDGER_CLOSE']


def test_prepared_draft_cannot_preview_on_a_different_plan(tmp_path, monkeypatch, flowhost):
    module, calls, ChangeStop = flowhost
    monkeypatch.setenv('IRONMAN_OPERATION_DRAFT_STORE', str(tmp_path/'drafts.sqlite3'))
    one = module.unified_changeset_flow.fn(
        {'schema':'IRONMAN_OPERATION_INPUT_V1','items':[
            item('plan.workout.patch', 'patch01', container_id=501, resource_id=31)]},
        'unused', mode='prepare')
    preview = {'schema':'IRONMAN_DRAFT_PREVIEW_INPUT_V1',
               'request_id':one['request_id'],
               'after_images':{'patch01':{'title':'updated'}},'pinned_revision':'a'*40}
    wrong = [{'kind':'plan.workout.patch', 'target':{
        'provider':'trainingpeaks','owner_id':2116886,
        'container_kind':'training_plan','container_id':902,'resource_id':31}}]
    with pytest.raises(ChangeStop, match='STOP_TARGET_MISMATCH'):
        module.unified_changeset_flow.fn(preview, str(tmp_path/'ledger.sqlite3'),
                                         mode='preview_draft', requested_targets=wrong)
    assert calls == ['CHANGESET_VALIDATION']
    assert not (tmp_path/'ledger.sqlite3').exists()


def test_unverified_new_plan_stays_prepare_only_even_if_after_image_is_forged(tmp_path, monkeypatch, flowhost):
    module, calls, _ = flowhost
    monkeypatch.setenv('IRONMAN_OPERATION_DRAFT_STORE', str(tmp_path/'drafts.sqlite3'))
    request_id = module.unified_changeset_flow.fn(request(), 'unused', mode='prepare')['request_id']
    with pytest.raises(Exception, match='PREVIEW_ADAPTER_NOT_RELEASED'):
        module.unified_changeset_flow.fn(
            {'schema':'IRONMAN_DRAFT_PREVIEW_INPUT_V1', 'request_id':request_id,
             'after_images': {'newplan':{},'newrun':{},'newnote':{},'attachpdf':{}},
             'pinned_revision':'a'*40}, str(tmp_path/'ledger.sqlite3'),
            mode='preview_draft', requested_targets=[])
    assert not calls
    assert not (tmp_path/'ledger.sqlite3').exists()
