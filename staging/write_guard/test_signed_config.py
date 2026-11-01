"""Focused tests of signed-approval runtime bootstrapping; no Google credentials."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from authenticated_bridge import SignedApproval, SignedApprovalAuthorizer
from guard import Patch
from inbound_api import load_trusted_config


def setup_files(tmp_path, key_hex=None):
    patch = Patch('signed-operation-01', 'sandboxDoc98765', 'AUTO', 'revision-1',
                  'Original text', 'Original text IRONMAN_SIGNED_TEST_20261101',
                  'IRONMAN_SIGNED_TEST_20261101', 'operator-grant-01')
    key = bytes.fromhex(key_hex) if key_hex else b'Z'*32
    grant = SignedApproval(patch.approval_ref, patch.digest(), 'staging-actor',
                           (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(), 'main', '')
    import hmac
    sig=hmac.new(key, grant.signed_body(), hashlib.sha256).hexdigest()
    grant=SignedApproval(grant.approval_ref, grant.patch_digest, grant.actor, grant.expires_at, grant.key_id, sig)
    def owned(name, obj):
        p=tmp_path/name
        p.write_text(json.dumps(obj), encoding='utf-8')
        p.chmod(0o600)
        return p
    keys=owned('keys.json', {'main':key.hex()})
    approvals=owned('approvals.json', [grant.__dict__])
    cfg=owned('runtime.json', {'actor':'staging-actor',
          'service_account_email':'staging@example.iam.gserviceaccount.com',
          'ledger_path':str(tmp_path/'ledger.db'),
          'bearer_token_sha256':hashlib.sha256(b'example-placeholder-token'*3).hexdigest(),
          'allowed_documents':['sandboxDoc98765'],
          'signed_policy':{'keys_file':str(keys),'approvals_file':str(approvals)}})
    return patch,keys,approvals,cfg


def test_signed_policy_loads_and_authorizes_exact_patch(tmp_path):
    patch,_,_,cfg=setup_files(tmp_path)
    authorized=load_trusted_config(str(cfg))
    assert isinstance(authorized.signed_authorizer, SignedApprovalAuthorizer)
    assert authorized.signed_authorizer.permits(patch)
    assert not authorized.signed_authorizer.permits(Patch(
        patch.operation_id, patch.document_id, patch.proven_path,
        patch.expected_revision, patch.old, patch.new+' extra',
        patch.checkpoint, patch.approval_ref))


def test_signed_policy_blocks_loose_keys_permissions(tmp_path):
    _,keys,_,cfg=setup_files(tmp_path)
    keys.chmod(0o644)
    with pytest.raises(ValueError,match='owner-only'):
        load_trusted_config(str(cfg))


def test_signed_policy_blocks_duplicate_approvals(tmp_path):
    _,_,approvals,cfg=setup_files(tmp_path)
    entries=json.loads(approvals.read_text())
    approvals.write_text(json.dumps(entries+entries))
    with pytest.raises(ValueError,match='Duplicate'):
        load_trusted_config(str(cfg))


def test_signed_policy_blocks_tampered_signature(tmp_path):
    patch,_,approvals,cfg=setup_files(tmp_path)
    entries=json.loads(approvals.read_text())
    entries[0]['signature']='0'*64
    approvals.write_text(json.dumps(entries))
    loaded=load_trusted_config(str(cfg))
    assert not loaded.signed_authorizer.permits(patch)


def test_signed_policy_blocks_symlink_key_file(tmp_path):
    _,keys,_,cfg=setup_files(tmp_path)
    linked=tmp_path/'alias.json'; linked.symlink_to(keys)
    data=json.loads(cfg.read_text()); data['signed_policy']['keys_file']=str(linked)
    cfg.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='non-symlink'):
        load_trusted_config(str(cfg))
