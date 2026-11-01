"""Bridge tests: deterministic HTTP fake and independent signed authorizer."""
from __future__ import annotations
import hashlib
import hmac
from datetime import datetime, timezone, timedelta

import pytest
from authenticated_bridge import (
    GoogleDocsRestConnector, SignedApproval, SignedApprovalAuthorizer,
    ScopedWriteService, approval_from_mapping, make_service_account_connector,
    StandingPolicy, StandingPolicyAuthorizer,
)
from guard import Patch, GuardError, ProviderError


class Response:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status
        self.status_code = status
    def raise_for_status(self):
        if self.status != 200:
            raise RuntimeError(f"HTTP {self.status}")
    def json(self): return self.body


class API:
    def __init__(self):
        self.doc = 'sandboxA1'
        self.text = 'Old value\n'
        self.revision = 'rev-A'
        self.writes = 0
        self.last_post = None
    def get(self, url, *, params, timeout):
        assert url == f'https://docs.googleapis.com/v1/documents/{self.doc}'
        assert params['includeTabsContent'] == 'true'
        assert 'revisionId' in params['fields']
        return Response({'documentId':self.doc,'revisionId':self.revision,
                         'tabs':[{'tabProperties':{'tabId':'t.0'},
                                  'documentTab':{'body':{'content':[
                                      {'sectionBreak':{}},
                                      {'paragraph':{'elements':[{'textRun':{'content':self.text}}]}}
                                   ]}}}]})
    def post(self,url,*,json,timeout):
        self.last_post=(url,json)
        assert url == f'https://docs.googleapis.com/v1/documents/{self.doc}:batchUpdate'
        if json['writeControl']['requiredRevisionId']!=self.revision: return Response({},400)
        req=json['requests'][0]['replaceAllText']
        assert req['tabsCriteria']=={'tabIds':['t.0']}
        old,new=req['containsText']['text'],req['replaceText']
        n=self.text.count(old)
        if n:
            self.text=self.text.replace(old,new);self.revision='rev-B';self.writes+=1
        return Response({'documentId':self.doc,'writeControl':{'requiredRevisionId':self.revision},
                         'replies':[{'replaceAllText':{'occurrencesChanged':n}}]})


def grant_for(patch, key=b'S'*32, *, actor='ironman-operator', expires=None):
    expires = expires or (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    g=SignedApproval(patch.approval_ref,patch.digest(),actor,expires,'main','')
    sig=hmac.new(key,g.signed_body(),hashlib.sha256).hexdigest()
    return SignedApproval(g.approval_ref,g.patch_digest,g.actor,g.expires_at,g.key_id,sig)


def patch():
    return Patch('op-1','sandboxA1','AUTO','rev-A','Old value',
                 'New value VERIFIED-MARK','VERIFIED-MARK','approval-1')


def authorizer(g, key=b'S'*32,actor='ironman-operator'):
    return SignedApprovalAuthorizer(actor=actor,trusted_approvals={g.approval_ref:g},trusted_keys={'main':key})


def test_bridge_end_to_end_with_signed_approval(tmp_path):
    api=API();p=patch();a=authorizer(grant_for(p))
    svc=ScopedWriteService(connector=GoogleDocsRestConnector(api),authorizer=a,
                           ledger_path=str(tmp_path/'ledger.sqlite'),allowed_documents={p.document_id})
    assert svc.execute(p)=='VERIFIED'
    assert svc.execute(p)=='ALREADY_VERIFIED'
    assert api.writes==1
    assert api.last_post[1]['writeControl']=={'requiredRevisionId':'rev-A'}


def test_signed_grant_rejects_mutated_payload():
    p=patch();a=authorizer(grant_for(p))
    forged=Patch('op-1','sandboxA1','AUTO','rev-A','Old value',
                 'DIFFERENT VERIFIED-MARK','VERIFIED-MARK','approval-1')
    assert not a.permits(forged)


def test_signed_grant_rejects_actor():
    p=patch();assert not authorizer(grant_for(p),actor='other-principal').permits(p)


def test_signed_grant_rejects_wrong_key():
    p=patch();assert not authorizer(grant_for(p),key=b'X'*32).permits(p)


def test_signed_grant_rejects_expired():
    p=patch();g=grant_for(p,expires=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
    assert not authorizer(g).permits(p)


def test_signed_grant_rejects_missing():
    p=patch();a=SignedApprovalAuthorizer(actor='ironman-operator',trusted_approvals={},trusted_keys={'main':b'S'*32})
    assert not a.permits(p)


def test_bridge_rejects_unknown_document(tmp_path):
    p=patch();api=API();svc=ScopedWriteService(connector=GoogleDocsRestConnector(api),
        authorizer=authorizer(grant_for(p)),ledger_path=str(tmp_path/'l.db'),allowed_documents={'another1'})
    with pytest.raises(GuardError,match='allowlist'): svc.execute(p)
    assert api.writes==0


def test_rest_connector_blocks_other_mutations():
    client=GoogleDocsRestConnector(API())
    with pytest.raises(ProviderError,match='mutation shape'):
        client.batch_update_document(document_id='sandboxA1',requests=[{'insertText':{'text':'hi'}}],
            write_control={'requiredRevisionId':'rev-A'})


def test_rest_connector_blocks_external_url():
    with pytest.raises(ProviderError,match='identifier'):
        GoogleDocsRestConnector(API()).get_document(document_id='https://evil.com',fields=__import__('google_docs_adapter').GoogleDocsConnectorAdapter.FIELDS)


def test_rest_requires_revision():
    client=GoogleDocsRestConnector(API())
    req=[{'replaceAllText':{'containsText':{'text':'a','matchCase':True},'replaceText':'b','tabsCriteria':{'tabIds':['t.0']}}}]
    with pytest.raises(ProviderError,match='requiredRevisionId'):
        client.batch_update_document(document_id='sandboxA1',requests=req,write_control={})


def test_connector_rejects_bad_fields():
    with pytest.raises(ProviderError,match='read fields'):
        GoogleDocsRestConnector(API()).get_document(document_id='sandboxA1',fields='*')


def test_invalid_approval_schema():
    with pytest.raises(ValueError): approval_from_mapping({'approval_ref':'one'})


def test_service_rejects_empty_allowlist(tmp_path):
    with pytest.raises(GuardError,match='allowlist'):
        ScopedWriteService(connector=GoogleDocsRestConnector(API()),authorizer=authorizer(grant_for(patch())),
           ledger_path=str(tmp_path/'ledger.db'),allowed_documents=set())


def test_no_unconfigured_real_adc_success():
    with pytest.raises(GuardError, match='Expected service identity'):
        make_service_account_connector(expected_email='')


def test_explicit_denial_is_persisted_and_never_replayed(tmp_path):
    class Denied(API):
        def __init__(self):
            super().__init__()
            self.attempts = 0
        def post(self, url, *, json, timeout):
            self.attempts += 1
            return Response({"error":{"code":403,"status":"PERMISSION_DENIED"}}, 403)
    from guard import ExplicitSecurityDenial
    api = Denied();p = patch()
    svc = ScopedWriteService(
        connector=GoogleDocsRestConnector(api), authorizer=authorizer(grant_for(p)),
        ledger_path=str(tmp_path/'ledger.sqlite'), allowed_documents={p.document_id})
    with pytest.raises(ExplicitSecurityDenial):
        svc.execute(p)
    assert api.attempts == 1
    with pytest.raises(GuardError,match='Prior explicit security denial'):
        svc.execute(p)
    assert api.attempts == 1


def test_unexpected_http_status_requires_recovery_not_fabricated_success(tmp_path):
    class Throttled(API):
        def post(self, url, *, json, timeout):
            return Response({"error":{"code":429}},429)
    from guard import ProviderError
    api=Throttled();p=patch()
    svc=ScopedWriteService(connector=GoogleDocsRestConnector(api),
          authorizer=authorizer(grant_for(p)),ledger_path=str(tmp_path/'journal.db'),allowed_documents={p.document_id})
    with pytest.raises(ProviderError): svc.execute(p)
    assert api.text=='Old value\n'


def test_service_denies_unsigned_approval_before_write(tmp_path):
    p=patch();good=grant_for(p)
    bad=SignedApproval(good.approval_ref,good.patch_digest,good.actor,good.expires_at,good.key_id,'0'*64)
    api=API()
    svc=ScopedWriteService(connector=GoogleDocsRestConnector(api),
         authorizer=authorizer(bad),ledger_path=str(tmp_path/'journal.db'),allowed_documents={p.document_id})
    with pytest.raises(GuardError,match='Authorization not verified'):
        svc.execute(p)
    assert api.writes==0


def test_standing_policy_reuses_class_without_per_document_signature(tmp_path):
    api=API()
    p=Patch('standing-op','sandboxA1','AUTO','rev-A','Old value',
        'Old value IRONMAN_GDOCS_CHECKPOINT_20261101','IRONMAN_GDOCS_CHECKPOINT_20261101',
        'standing-kb')
    policy=StandingPolicy('standing-kb','ironman-operator',frozenset({'sandboxA1'}),
          (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    auth=StandingPolicyAuthorizer(actor='ironman-operator',policy=policy)
    svc=ScopedWriteService(connector=GoogleDocsRestConnector(api),authorizer=auth,
        ledger_path=str(tmp_path/'ledger.db'),allowed_documents={'sandboxA1'})
    assert svc.execute(p)=='VERIFIED'
    assert svc.execute(p)=='ALREADY_VERIFIED'
    assert api.writes==1


def test_standing_policy_rejects_document_deletion():
    policy=StandingPolicy('standing-kb','ironman-operator',frozenset({'sandboxA1'}),
          (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    p=Patch('del-op','sandboxA1','AUTO','rev-A','Old value',
        'IRONMAN_DELETION_ATTEMPT','IRONMAN_DELETION_ATTEMPT','standing-kb')
    assert not StandingPolicyAuthorizer(actor='ironman-operator',policy=policy).permits(p)


def test_standing_policy_rejects_oversized_patch():
    policy=StandingPolicy('standing-kb','ironman-operator',frozenset({'sandboxA1'}),
          (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),max_replacement_chars=100)
    p=Patch('oversized','sandboxA1','AUTO','rev-A','Old value',
        'Old value'+('a'*101)+' IRONMAN_TEST','IRONMAN_TEST','standing-kb')
    assert not StandingPolicyAuthorizer(actor='ironman-operator',policy=policy).permits(p)


def test_standing_policy_rejects_other_document():
    policy=StandingPolicy('standing-kb','ironman-operator',frozenset({'sandboxB1'}),
          (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    p=Patch('other','sandboxA1','AUTO','rev-A','Old value',
        'Old value IRONMAN_TEST','IRONMAN_TEST','standing-kb')
    assert not StandingPolicyAuthorizer(actor='ironman-operator',policy=policy).permits(p)
