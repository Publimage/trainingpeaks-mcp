from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from inbound_api import TrustedConfig, build_app, load_trusted_config
from authenticated_bridge import StandingPolicy, StandingPolicyAuthorizer, ScopedWriteService, GoogleDocsRestConnector
from guard import GuardError, ExplicitSecurityDenial
from test_authenticated_bridge import API, Response

TOKEN = 't'*48
HASH = hashlib.sha256(TOKEN.encode()).hexdigest()
DOC = 'sandboxA1'
MARKER = 'IRONMAN_STANDING_TEST_MARKER'

def payload():
    return dict(operation_id='operation-01', document_id=DOC, expected_revision='rev-A',
                old='Old value', new='Old value '+MARKER, checkpoint=MARKER,
                approval_ref='standing-policy')


def setup(tmp_path, *, fake=None):
    fake = fake or API()
    policy = StandingPolicy(
        'standing-policy', 'staging-actor', frozenset({DOC}),
        (datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    cfg = TrustedConfig('staging-actor','staging@example.iam.gserviceaccount.com',
                        str(tmp_path/'ledger.sqlite'),HASH,frozenset({DOC}),standing_policy=policy)
    calls=[]
    def service():
        calls.append(1)
        return ScopedWriteService(
            connector=GoogleDocsRestConnector(fake),
            authorizer=StandingPolicyAuthorizer(actor='staging-actor',policy=policy),
            ledger_path=cfg.ledger_path,allowed_documents={DOC})
    client = TestClient(build_app(cfg, service))
    return client,fake,calls,cfg


def auth(): return {'Authorization':'Bearer '+TOKEN}


def test_auth_required_and_no_service_start_before_auth(tmp_path):
    client,fake,calls,_=setup(tmp_path)
    assert client.post('/v1/docs/replace',json=payload()).status_code == 401
    assert client.get('/v1/operations/operation-01').status_code == 401
    assert calls == []
    assert fake.writes == 0


def test_bad_token_no_service_calls(tmp_path):
    client,fake,calls,_=setup(tmp_path)
    assert client.post('/v1/docs/replace',json=payload(),headers={'Authorization':'Bearer ' + 'x'*48}).status_code == 401
    assert calls == []


def test_end_to_end_inbound_fake_and_idempotency(tmp_path):
    client,fake,calls,_=setup(tmp_path)
    r=client.post('/v1/docs/replace',json=payload(),headers=auth())
    assert r.status_code == 200, r.text
    assert r.json()['status']=='VERIFIED'
    assert client.get('/v1/operations/operation-01',headers=auth()).json()['status']=='VERIFIED'
    again=client.post('/v1/docs/replace',json=payload(),headers=auth())
    assert again.status_code==200 and again.json()['status']=='ALREADY_VERIFIED'
    assert fake.writes==1


def test_unknown_doc_denied_before_service_factory(tmp_path):
    client,fake,calls,_=setup(tmp_path)
    req=payload();req['document_id']='anotherdoc123'
    r=client.post('/v1/docs/replace',json=req,headers=auth())
    assert r.status_code==403
    assert not calls


def test_cannot_supply_policy_or_token_as_request_field(tmp_path):
    client,fake,calls,_=setup(tmp_path)
    req=payload();req['policy']={'allowed_documents':[DOC]}
    assert client.post('/v1/docs/replace',json=req,headers=auth()).status_code==422
    req=payload();req['credentials']='FAKE'
    assert client.post('/v1/docs/replace',json=req,headers=auth()).status_code==422
    assert not calls


def test_changed_payload_with_same_operation_id_conflicts(tmp_path):
    client,fake,_,_=setup(tmp_path)
    assert client.post('/v1/docs/replace',json=payload(),headers=auth()).status_code==200
    req=payload();req['new']='Old value IRONMAN_DIFFERENT_MARKER';req['checkpoint']='IRONMAN_DIFFERENT_MARKER'
    r=client.post('/v1/docs/replace',json=req,headers=auth())
    assert r.status_code==409 and fake.writes==1


def test_denial_persists_no_repeat(tmp_path):
    class Deny(API):
        def __init__(self): super().__init__();self.attempts=0
        def post(self,*args,**kwargs): self.attempts+=1;return Response({'error':{'code':403}},403)
    f=Deny();client,_,_,_=setup(tmp_path,fake=f)
    assert client.post('/v1/docs/replace',json=payload(),headers=auth()).status_code==403
    assert client.post('/v1/docs/replace',json=payload(),headers=auth()).status_code==403
    assert f.attempts==1
    assert client.get('/v1/operations/operation-01',headers=auth()).json()['status']=='SECURITY_DENIED'


def test_live_endpoint_is_not_claim_of_provider_readiness(tmp_path):
    client,_,_,_=setup(tmp_path)
    assert client.get('/health/live').json()=={'state':'running'}


def test_operation_status_not_found(tmp_path):
    client,_,_,_=setup(tmp_path)
    # If ledger not created yet, first service invocation initializes it through a safe reject.
    req=payload();req['checkpoint']='NO_MARK'
    client.post('/v1/docs/replace',json=req,headers=auth())
    assert client.get('/v1/operations/unknown-operation',headers=auth()).status_code==404


def test_config_secure_file_and_rejects_loose_permissions(tmp_path):
    config={
      'actor':'staging-actor', 'service_account_email':'staging@example.iam.gserviceaccount.com',
      'ledger_path':str(tmp_path/'ledger.db'), 'bearer_token_sha256':HASH,
      'allowed_documents':[DOC],
      'standing_policy':{
         'policy_id':'standing-policy', 'actor':'staging-actor','allowed_documents':[DOC],
         'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
         'max_replacement_chars':1600
      }
    }
    filename=tmp_path/'config.json';filename.write_text(json.dumps(config));os.chmod(filename,0o600)
    loaded=load_trusted_config(str(filename))
    assert loaded.allowed_documents==frozenset([DOC])
    os.chmod(filename,0o644)
    with pytest.raises(ValueError,match='private owner-only'):
       load_trusted_config(str(filename))


def test_empty_scope_cannot_start(tmp_path):
    _,_,_,cfg=setup(tmp_path)
    cfg=TrustedConfig(cfg.actor,cfg.service_account_email,cfg.ledger_path,cfg.bearer_token_sha256,frozenset(),standing_policy=cfg.standing_policy)
    with pytest.raises(ValueError,match='allowlist'):
       build_app(cfg,lambda:None)


def test_config_secret_not_leaked_on_bad_token(tmp_path):
    client,_,_,_=setup(tmp_path)
    r=client.post('/v1/docs/replace',json=payload(),headers={'Authorization':'Bearer '+ 'bad'*20})
    assert TOKEN not in r.text and HASH not in r.text


def test_input_rejects_extra_fields(tmp_path):
    client,_,_,_=setup(tmp_path)
    req=payload();req['proven_path']='UNVERIFIED-CUSTOM'
    assert client.post('/v1/docs/replace',json=req,headers=auth()).status_code==422
