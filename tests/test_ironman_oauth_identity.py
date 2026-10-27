"""Authentication profile only: synthetic IdP, no HTTP/issuer/runtime install."""
import copy

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from test_ironman_authorization import signed

from scripts.ironman_jobs.ironman_authorization import (
    OAuthHumanIdentity,
    OAuthHumanIdentityVerifier,
    Principal,
    SignedIdentityVerifier,
)


@pytest.fixture
def oauth_identity():
    key = ed25519.Ed25519PrivateKey.generate()
    config = {"issuer": "https://synthetic-idp.invalid", "audience": "https://synthetic-mcp.invalid/mcp",
        "required_scope": "ironman:operator", "human_subjects": ["human-42"], "client_ids": ["chatgpt-client"],
        "keys": {"test-key": {"algorithm": "EdDSA", "public_key_pem": key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()}}}
    claims = {"iss": config["issuer"], "aud": config["audience"], "scope": config["required_scope"],
        "sub": "human-42", "client_id": "chatgpt-client", "jti": "access-1", "iat": 900, "exp": 1100}
    def token(changes=None, typ="at+jwt", signer=None):
        return signed(signer or key, {**claims, **(changes or {})}, {"kid": "test-key", "alg": "EdDSA", "typ": typ})
    return config, claims, token


def test_verified_oauth_human_is_not_worker_delegation_or_operation_approval(oauth_identity, tmp_path):
    config, _, token = oauth_identity
    identity = OAuthHumanIdentityVerifier(config, clock=lambda: 1000).verify(token())
    assert isinstance(identity, OAuthHumanIdentity) and not isinstance(identity, Principal)
    assert (identity.issuer, identity.subject) == (config["issuer"], "human-42")
    assert not hasattr(identity, "invocation_id") and not hasattr(identity, "command_sha256")
    worker = SignedIdentityVerifier({k: v for k, v in config.items() if k not in {"human_subjects", "client_ids"}} |
        {"administrators": []}, clock=lambda: 1000)
    # An access token does not gain a scheduler invocation just by being signed.
    with pytest.raises(PermissionError):
        worker.verify(token())
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("changes", [
    {"iss": "https://wrong.invalid"}, {"aud": "google-api"}, {"scope": "openid profile"},
    {"sub": "machine-client", "email": "owner@example.invalid"}, {"sub": None},
    {"client_id": "another-client"}, {"client_id": None}, {"jti": None}, {"exp": 1000},
    {"iat": 1001}, {"nbf": 1001}, {"nbf": True},
])
def test_oauth_identity_requires_exact_resource_human_client_and_current_token(oauth_identity, changes):
    config, _, token = oauth_identity
    with pytest.raises(PermissionError):
        OAuthHumanIdentityVerifier(config, clock=lambda: 1000).verify(token(changes))


@pytest.mark.parametrize("typ", ["JWT", "id_token", "anything"])
def test_id_tokens_and_unattested_token_profiles_are_not_access_tokens(oauth_identity, typ):
    config, _, token = oauth_identity
    with pytest.raises(PermissionError):
        OAuthHumanIdentityVerifier(config, clock=lambda: 1000).verify(token(typ=typ))


def test_access_signature_is_verified_and_refresh_keeps_the_human_not_token_identity(oauth_identity):
    config, _, token = oauth_identity
    verifier = OAuthHumanIdentityVerifier(config, clock=lambda: 1000)
    with pytest.raises(PermissionError, match="ASSERTION_SIGNATURE_INVALID"):
        verifier.verify(token(signer=ed25519.Ed25519PrivateKey.generate()))
    first, renewed = verifier.verify(token()), verifier.verify(token({"jti": "access-2", "nbf": 950}))
    assert (first.issuer, first.subject) == (renewed.issuer, renewed.subject)
    assert first.token_id != renewed.token_id


@pytest.mark.parametrize("field", ["human_subjects", "client_ids"])
def test_unconfigured_human_or_client_binding_cannot_install_verifier(oauth_identity, field):
    config = copy.deepcopy(oauth_identity[0])
    config[field] = []
    with pytest.raises(PermissionError, match="OAUTH_HUMAN_AND_CLIENT_BINDINGS_REQUIRED"):
        OAuthHumanIdentityVerifier(config)


async def test_sdk_port_preserves_human_session_owner_instead_of_shared_client(oauth_identity):
    from mcp.server.auth.provider import principal_components

    from scripts.ironman_jobs.ironman_authorization import OAuthMCPTokenVerifier

    config, _, token = oauth_identity
    config["human_subjects"].append("human-43")
    checked = []

    async def current(identity):
        checked.append(identity.subject)
        return True

    sdk = OAuthMCPTokenVerifier(OAuthHumanIdentityVerifier(config, clock=lambda: 1000), revocations_current=current)
    first = await sdk.verify_token(token())
    renewed = await sdk.verify_token(token({"jti": "access-2"}))
    another = await sdk.verify_token(token({"sub": "human-43"}))
    assert principal_components(first) == principal_components(renewed)
    assert principal_components(first) != principal_components(another)
    assert first.client_id == another.client_id
    assert first.resource == config["audience"]
    assert checked == ["human-42", "human-42", "human-43"]


@pytest.mark.parametrize("feed", ["stale", "revoked", "unavailable", "expires-during-check"])
async def test_sdk_admission_does_not_substitute_signature_for_current_revocations(oauth_identity, feed):
    from scripts.ironman_jobs.ironman_authorization import OAuthMCPTokenVerifier

    config, _, token = oauth_identity
    now = [1000]

    async def current(_):
        if feed == "unavailable":
            raise ConnectionError("SYNTHETIC_FEED_UNAVAILABLE")
        if feed == "expires-during-check":
            now[0] = 1100
            return True
        return False

    sdk = OAuthMCPTokenVerifier(OAuthHumanIdentityVerifier(config, clock=lambda: now[0]), revocations_current=current)
    assert await sdk.verify_token(token()) is None


def test_sdk_port_cannot_install_without_real_revocation_policy(oauth_identity):
    from scripts.ironman_jobs.ironman_authorization import OAuthMCPTokenVerifier

    with pytest.raises(PermissionError, match="OAUTH_IDENTITY_AND_REVOCATION_PORT_REQUIRED"):
        OAuthMCPTokenVerifier(OAuthHumanIdentityVerifier(oauth_identity[0]), revocations_current=None)
