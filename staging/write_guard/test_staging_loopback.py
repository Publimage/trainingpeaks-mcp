"""Local HTTP transport smoke test. No real Google credential or provider write."""
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def test_loopback_unauthorized_and_no_real_google_write(tmp_path):
    token = secrets.token_urlsafe(48)
    port = _free_port()
    cfg = {
        'actor': 'smoke-test-actor',
        'service_account_email': 'nonexistent-sandbox@example.iam.gserviceaccount.com',
        'ledger_path': str(tmp_path/'journal.sqlite3'),
        'bearer_token_sha256': hashlib.sha256(token.encode()).hexdigest(),
        'allowed_documents': ['sandboxDocABC01'],
        'standing_policy': {
            'policy_id': 'smoke-policy', 'actor': 'smoke-test-actor',
            'allowed_documents': ['sandboxDocABC01'],
            'expires_at': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
            'max_replacement_chars': 1600,
        },
    }
    path=tmp_path/'private.json';path.write_text(json.dumps(cfg));path.chmod(0o600)
    env=os.environ.copy();env['WG_CONFIG_PATH']=str(path);env['WG_STAGING_PORT']=str(port)
    proc=subprocess.Popen([sys.executable,'staging_server.py'],cwd=str(Path(__file__).parent),env=env,
                          stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        base=f'http://127.0.0.1:{port}'
        for _ in range(80):
            try:
                with urllib.request.urlopen(base+'/health/live', timeout=0.5) as response:
                    assert json.loads(response.read()) == {'state': 'running'}
                    break
            except (urllib.error.URLError, TimeoutError):
                if proc.poll() is not None:
                    raise AssertionError('Staging server failed to start')
                time.sleep(0.05)
        else:
            raise AssertionError('Loopback server did not start')
        data=json.dumps({
            'operation_id':'smoke-operation-01','document_id':'sandboxDocABC01',
            'expected_revision':'not-a-real-revision','old':'Before text',
            'new':'Before text IRONMAN_TEST_ONLY','checkpoint':'IRONMAN_TEST_ONLY',
            'approval_ref':'smoke-policy',
        }).encode()
        req=urllib.request.Request(base+'/v1/docs/replace',data=data,
                                   headers={'Content-Type':'application/json'},method='POST')
        try:
            urllib.request.urlopen(req,timeout=2)
            assert False, 'unauthenticated request should fail'
        except urllib.error.HTTPError as exc:
            assert exc.code==401
        # No ADC identity exists, therefore the route must fail closed, not report a write.
        req.add_header('Authorization','Bearer '+token)
        try:
            urllib.request.urlopen(req,timeout=2)
            assert False, 'unconfigured Google identity must not permit a write'
        except urllib.error.HTTPError as exc:
            assert exc.code==503
        assert not Path(cfg['ledger_path']).exists()
    finally:
        proc.terminate()
        try: proc.communicate(timeout=3)
        except subprocess.TimeoutExpired: proc.kill();proc.communicate(timeout=3)
