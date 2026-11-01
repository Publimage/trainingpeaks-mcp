"""Read-only provider identity preflight; never exercises a Google write."""
import hashlib, json
from datetime import datetime, timedelta, timezone
from inbound_api import TrustedConfig, load_trusted_config
from authenticated_bridge import StandingPolicy
from provider_preflight import check_readiness
from test_authenticated_bridge import API
from authenticated_bridge import GoogleDocsRestConnector


def cfg_file(tmp_path):
    raw={
      'actor':'staging-actor',
      'service_account_email':'staging@example.iam.gserviceaccount.com',
      'ledger_path':str(tmp_path/'journal.db'),
      'bearer_token_sha256':hashlib.sha256(b'a'*48).hexdigest(),
      'allowed_documents':['sandboxA1'],
      'standing_policy':{
        'policy_id':'standing-kb', 'actor':'staging-actor',
        'allowed_documents':['sandboxA1'],
        'expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(),
        'max_replacement_chars':1600
      }
    }
    p=tmp_path/'config.json';p.write_text(json.dumps(raw));p.chmod(0o600)
    return str(p)


def test_readiness_reports_provider_access_without_writing(tmp_path):
    api=API()
    report=check_readiness(cfg_file(tmp_path),connector_factory=lambda *,expected_email:GoogleDocsRestConnector(api))
    assert report['state']=='READONLY_PROVIDER_ACCESS_VERIFIED'
    assert report['documents_verified']==1
    assert report['write_tested'] is False
    assert api.writes==0
    assert 'text' not in report['documents'][0]
    assert not (tmp_path/'journal.db').exists()


def test_readiness_fails_when_credentials_missing_without_writing(tmp_path):
    def deny(*,expected_email): raise RuntimeError('Missing ADC')
    report=check_readiness(cfg_file(tmp_path),connector_factory=deny)
    assert report['state']=='GOOGLE_IDENTITY_UNAVAILABLE'
    assert report['reason_class']=='RuntimeError'


def test_readiness_fails_on_provider_read_denial_without_writing(tmp_path):
    class Denied(API):
        def get(self,*args,**kwargs): raise RuntimeError('Access denied')
    report=check_readiness(cfg_file(tmp_path),connector_factory=lambda *,expected_email:GoogleDocsRestConnector(Denied()))
    assert report['state']=='GOOGLE_DOCUMENT_UNAVAILABLE'
    assert report['documents_verified']==0
