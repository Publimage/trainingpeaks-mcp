import sqlite3
import pytest
from guard import DocsWriteGuard, Patch, Document, GuardError, ProviderError, ExplicitSecurityDenial, ReconciliationRequired


class FakeDocs:
    def __init__(self):
        self.docs = {'doc-1': Document('r1', 'Before block.\n')}
        self.writes = 0
        self.raise_after_write = False
        self.fail_before_write = False
        self.security_denial = False
        self.crash_before_write = False
        self.crash_after_write = False
        self.fail_read_after_write = False

    def read(self, document_id):
        if self.fail_read_after_write and self.writes:
            raise OSError('temporary read outage')
        return self.docs[document_id]

    def replace_once(self, document_id, required_revision, old, new):
        if self.crash_before_write:
            raise SystemExit('simulated process death before provider call')
        if self.security_denial:
            raise ExplicitSecurityDenial('explicit provider denial')
        if self.fail_before_write:
            raise RuntimeError('network error')
        d = self.docs[document_id]
        if d.revision != required_revision:
            raise RuntimeError('revision conflict')
        self.docs[document_id] = Document('r2', d.text.replace(old, new, 1))
        self.writes += 1
        if self.crash_after_write:
            raise SystemExit('simulated process death after provider committed')
        if self.raise_after_write:
            raise RuntimeError('server returned timeout after completing write')


class FakeAuth:
    def __init__(self):
        self.enabled = True
        self.approved_revision = 'r1'

    def permits(self, p):
        # Deliberately bind fake authorization to the entire mutation payload,
        # not just the document and operation ID. AUTO and named verified paths
        # are the same capability and are intentionally both accepted.
        return (self.enabled and p.approval_ref == 'approved-scope' and
                p.document_id == 'doc-1' and p.operation_id == 'op-1' and
                p.expected_revision == self.approved_revision and p.old == 'Before block.' and
                p.new == 'Before block. CHECKPOINT-1' and p.checkpoint == 'CHECKPOINT-1')


@pytest.fixture
def ctx(tmp_path):
    f = FakeDocs()
    auth = FakeAuth()
    g = DocsWriteGuard(f, auth, str(tmp_path / 'ledger.db'), {'doc-1'})
    p = Patch('op-1', 'doc-1', 'DRIVE-DOC-004', 'r1', 'Before block.', 'Before block. CHECKPOINT-1', 'CHECKPOINT-1', 'approved-scope')
    return f, g, p


def test_success_verified(ctx):
    f,g,p = ctx
    assert g.execute(p) == 'VERIFIED'
    assert f.writes == 1
    assert 'CHECKPOINT-1' in f.read('doc-1').text


def test_idempotent_repeat(ctx):
    f,g,p = ctx
    assert g.execute(p) == 'VERIFIED'
    assert g.execute(p) == 'ALREADY_VERIFIED'
    assert f.writes == 1


def test_idempotent_after_reopen(ctx, tmp_path):
    f,g,p = ctx
    g.execute(p)
    new_guard = DocsWriteGuard(f, FakeAuth(), g.ledger_path, {'doc-1'})
    assert new_guard.execute(p) == 'ALREADY_VERIFIED'
    assert f.writes == 1


def test_unknown_path_denied(ctx):
    f,g,p = ctx
    q = Patch(**{**p.__dict__, 'proven_path':'INVENTED-PATH'})
    with pytest.raises(GuardError): g.execute(q)
    assert f.writes == 0


def test_unapproved_document_denied(ctx):
    f,g,p = ctx
    q = Patch(**{**p.__dict__, 'document_id':'some-other-doc'})
    with pytest.raises(GuardError): g.execute(q)
    assert f.writes == 0


def test_missing_approval_denied(ctx):
    f,g,p = ctx
    q = Patch(**{**p.__dict__, 'approval_ref':''})
    with pytest.raises(GuardError): g.execute(q)
    assert f.writes == 0


def test_revision_conflict_denied(ctx):
    f,g,p = ctx
    f.docs['doc-1'] = Document('r9', 'Before block.\n')
    with pytest.raises(GuardError): g.execute(p)
    assert f.writes == 0


def test_duplicate_anchor_denied(ctx):
    f,g,p = ctx
    f.docs['doc-1'] = Document('r1', 'Before block.\nBefore block.\n')
    with pytest.raises(GuardError): g.execute(p)
    assert f.writes == 0


def test_changed_payload_same_operation_rejected(ctx):
    f,g,p = ctx
    g.execute(p)
    q = Patch(**{**p.__dict__, 'new':'Before block. CHECKPOINT-1 revised'})
    with pytest.raises(GuardError): g.execute(q)
    assert f.writes == 1


def test_timeout_after_write_readback_prevents_duplicate(ctx):
    f,g,p = ctx
    f.raise_after_write=True
    assert g.execute(p) == 'VERIFIED'
    assert g.execute(p) == 'ALREADY_VERIFIED'
    assert f.writes == 1


def test_failure_before_write_cannot_claim_success(ctx):
    f,g,p = ctx
    f.fail_before_write = True
    with pytest.raises(ProviderError): g.execute(p)
    assert f.writes == 0
    f.fail_before_write = False
    assert g.execute(p) == 'VERIFIED'
    assert f.writes == 1


def test_external_deletion_after_verified_is_blocked(ctx):
    f,g,p = ctx
    g.execute(p)
    f.docs['doc-1'] = Document('r3', 'Before block.\n')
    with pytest.raises(GuardError): g.execute(p)
    assert f.writes == 1


def test_checkpoint_present_wrong_body_denied(ctx):
    f,g,p = ctx
    f.docs['doc-1'] = Document('r3', 'External CHECKPOINT-1 partial content\n')
    with pytest.raises(GuardError): g.execute(p)
    assert f.writes == 0


def test_forged_approval_is_denied(ctx):
    f,g,p = ctx
    q = Patch(**{**p.__dict__, 'approval_ref':'forged-token'})
    with pytest.raises(GuardError): g.execute(q)
    assert f.writes == 0


def test_explicit_security_denial_is_not_retried(ctx):
    f,g,p = ctx
    f.security_denial = True
    with pytest.raises(ExplicitSecurityDenial): g.execute(p)
    f.security_denial = False
    with pytest.raises(GuardError, match='no retry'): g.execute(p)
    assert f.writes == 0


def _journal_state(guard, op='op-1'):
    with sqlite3.connect(guard.ledger_path) as db:
        row = db.execute('SELECT state FROM operations WHERE operation_id=?', (op,)).fetchone()
    return row[0] if row else None


def test_authorization_is_bound_to_entire_delta(ctx):
    f, g, p = ctx
    malicious = Patch(**{**p.__dict__, 'new': 'Before block. CHECKPOINT-1 extra change'})
    with pytest.raises(GuardError, match='exact modification'):
        g.execute(malicious)
    assert f.writes == 0
    assert _journal_state(g) is None


def test_inflight_journal_survives_crash_after_provider_write(ctx):
    f, g, p = ctx
    f.crash_after_write = True
    with pytest.raises(SystemExit):
        g.execute(p)
    assert _journal_state(g) == 'IN_FLIGHT'
    f.crash_after_write = False
    # A NEW process can prove the write already happened and avoids a duplicate.
    recovered = DocsWriteGuard(f, FakeAuth(), g.ledger_path, {'doc-1'})
    assert recovered.execute(p) == 'ALREADY_VERIFIED'
    assert _journal_state(recovered) == 'VERIFIED'
    assert f.writes == 1


def test_crash_before_write_is_not_blindly_replayed(ctx):
    f, g, p = ctx
    f.crash_before_write = True
    with pytest.raises(SystemExit):
        g.execute(p)
    assert _journal_state(g) == 'IN_FLIGHT'
    f.crash_before_write = False
    recovered = DocsWriteGuard(f, FakeAuth(), g.ledger_path, {'doc-1'})
    with pytest.raises(ReconciliationRequired):
        recovered.execute(p)
    assert f.writes == 0


def test_post_write_readback_failure_persists_uncertainty_then_recovers(ctx):
    f, g, p = ctx
    f.fail_read_after_write = True
    with pytest.raises(ReconciliationRequired, match='readback unavailable'):
        g.execute(p)
    assert _journal_state(g) == 'UNCERTAIN'
    assert f.writes == 1
    f.fail_read_after_write = False
    restarted = DocsWriteGuard(f, FakeAuth(), g.ledger_path, {'doc-1'})
    assert restarted.execute(p) == 'ALREADY_VERIFIED'
    assert f.writes == 1


def test_explicit_denial_stays_persisted_across_restart(ctx):
    f, g, p = ctx
    f.security_denial = True
    with pytest.raises(ExplicitSecurityDenial):
        g.execute(p)
    assert _journal_state(g) == 'SECURITY_DENIED'
    f.security_denial = False
    restarted = DocsWriteGuard(f, FakeAuth(), g.ledger_path, {'doc-1'})
    with pytest.raises(GuardError, match='no retry'):
        restarted.execute(p)
    assert f.writes == 0
