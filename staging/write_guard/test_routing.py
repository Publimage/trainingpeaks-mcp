from dataclasses import replace
import pytest
from guard import DocsWriteGuard, Patch, GuardError
from routing import Capability, CapabilityRegistry, DOCS_CAPABILITIES
from test_guard import FakeDocs, FakeAuth


def test_generic_docs_path_exists_without_unique_per_document_certification(tmp_path):
    provider = FakeDocs()
    guard = DocsWriteGuard(provider, FakeAuth(), str(tmp_path / 'ledger.db'), {'doc-1'})
    patch = Patch('op-1', 'doc-1', 'AUTO', 'r1', 'Before block.',
                  'Before block. CHECKPOINT-1', 'CHECKPOINT-1', 'approved-scope')
    assert guard.execute(patch) == 'VERIFIED'
    assert guard.execute(patch) == 'ALREADY_VERIFIED'
    assert provider.writes == 1


def test_auto_picks_only_verified_resource_class():
    x = DOCS_CAPABILITIES.resolve('google_docs', 'replace_text_once')
    assert x.state == 'READY'
    assert x.path_id == 'DRIVE-DOC-004'
    assert DOCS_CAPABILITIES.resolve('trainingpeaks', 'delete_plan').state == 'VALIDATION_REQUIRED'


def test_missing_one_path_does_not_block_other_capabilities():
    reg = CapabilityRegistry((
        Capability('google_docs','replace_text_once','DRIVE-DOC-004','readback evidence'),
        Capability('trainingpeaks','new_feature','NEW-PATH','',state='CANDIDATE'),
    ))
    assert reg.resolve('trainingpeaks','new_feature').state == 'CANARY_REQUIRED'
    assert reg.resolve('google_docs','replace_text_once').state == 'READY'


def test_candidate_dry_run_must_not_become_live_certification():
    reg = CapabilityRegistry((Capability('social','new_media','CAND-1','',state='CANDIDATE'),))
    assert reg.evaluate_candidate_offline('social','new_media',lambda: True).state == 'CANARY_REQUIRED'
    assert reg.resolve('social','new_media').state == 'CANARY_REQUIRED'


def test_probe_failed_has_action_without_unsafe_write():
    reg = CapabilityRegistry(())
    d = reg.evaluate_candidate_offline('social','unknown',lambda: False)
    assert d.state == 'VALIDATION_REQUIRED'
    assert d.path_id is None


def test_missing_capability_cannot_be_forced_with_auto(tmp_path):
    provider = FakeDocs()
    guard = DocsWriteGuard(provider, FakeAuth(), str(tmp_path / 'ledger.db'), {'doc-1'}, CapabilityRegistry(()))
    patch = Patch('op-1', 'doc-1', 'AUTO', 'r1', 'Before block.',
                  'Before block. CHECKPOINT-1', 'CHECKPOINT-1', 'approved-scope')
    with pytest.raises(GuardError,match='capability not verified'):
        guard.execute(patch)
    assert provider.writes == 0


def test_deprecated_explicit_path_cannot_force_execution(tmp_path):
    provider = FakeDocs()
    reg = CapabilityRegistry((
        Capability('google_docs','replace_text_once','DRIVE-DOC-004','verified provider evidence'),
        Capability('google_docs','replace_text_once','KB-DOCS-RELIABLE-WRITE-033','old evidence',state='DEPRECATED'),
    ))
    guard = DocsWriteGuard(provider, FakeAuth(), str(tmp_path / 'ledger.db'), {'doc-1'}, reg)
    patch = Patch('op-1', 'doc-1', 'KB-DOCS-RELIABLE-WRITE-033', 'r1',
                  'Before block.', 'Before block. CHECKPOINT-1', 'CHECKPOINT-1', 'approved-scope')
    with pytest.raises(GuardError,match='lacks verified evidence'):
        guard.execute(patch)
    assert provider.writes == 0


def test_auto_does_not_bypass_authorizer(tmp_path):
    provider = FakeDocs()
    auth=FakeAuth()
    auth.enabled=False
    guard=DocsWriteGuard(provider,auth,str(tmp_path/'ledger.db'),{'doc-1'})
    patch=Patch('op-1','doc-1','AUTO','r1','Before block.',
                'Before block. CHECKPOINT-1','CHECKPOINT-1','approved-scope')
    with pytest.raises(GuardError,match='Authorization not verified'):
        guard.execute(patch)
    assert provider.writes == 0


def test_auto_does_not_bypass_revision(tmp_path):
    provider=FakeDocs()
    auth=FakeAuth()
    auth.approved_revision='badrev'  # independently approved, but provider revision is stale
    guard=DocsWriteGuard(provider,auth,str(tmp_path/'ledger.db'),{'doc-1'})
    patch=Patch('op-1','doc-1','AUTO','badrev','Before block.',
                'Before block. CHECKPOINT-1','CHECKPOINT-1','approved-scope')
    with pytest.raises(GuardError,match='Stale revision'):
        guard.execute(patch)
    assert provider.writes==0
