"""New HTTP boundary only: real SDK/ASGI and test-only IdP, no worker/provider."""

import asyncio
import base64
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from test_ironman_authorization import signed

from scripts.ironman_jobs.ironman_authorization import OAuthHumanIdentityVerifier, OAuthMCPTokenVerifier
from tp_mcp import server
from tp_mcp.operator_http import OperatorHTTPConfig, current_http_access_token, guard_operator_http
from tp_mcp.operator_runtime import OperatorBindings, bind_operator_runtime

CONFIG = OperatorHTTPConfig(
    "https://mcp.synthetic.invalid/mcp", "https://idp.synthetic.invalid", "ironman:operator", "127.0.0.1", 8443
)
COMMAND = {"mode": "prepare", "manifest": {"items": []}, "requested_targets": []}


@pytest.fixture
def boundary():
    key = ed25519.Ed25519PrivateKey.generate()
    trust = {
        "issuer": CONFIG.issuer,
        "audience": CONFIG.resource_url,
        "required_scope": CONFIG.scope,
        "human_subjects": ["human-a", "human-b"],
        "client_ids": ["shared-chatgpt-client"],
        "keys": {
            "test-key": {
                "algorithm": "EdDSA",
                "public_key_pem": key.public_key()
                .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
                .decode(),
            }
        },
    }
    state = {"checks": 0, "deny_after": None, "unavailable": False, "runtime": True}
    admitted, invoked = [], []

    async def revocations(identity):
        state["checks"] += 1
        if state["unavailable"]:
            raise ConnectionError("SYNTHETIC_FEED_UNAVAILABLE")
        return state["deny_after"] is None or state["checks"] <= state["deny_after"]

    verifier = OAuthMCPTokenVerifier(OAuthHumanIdentityVerifier(trust), revocations_current=revocations)

    def token(subject="human-a", **claims):
        now = int(time.time())
        return signed(
            key,
            {
                "iss": CONFIG.issuer,
                "aud": CONFIG.resource_url,
                "sub": subject,
                "client_id": "shared-chatgpt-client",
                "scope": CONFIG.scope,
                "jti": "access-1",
                "iat": now - 1,
                "exp": now + 600,
                **claims,
            },
            {"alg": "EdDSA", "kid": "test-key", "typ": "at+jwt"},
        )

    def bindings_for(access):
        admitted.append(access.subject)
        if not state["runtime"]:
            return None

        def invoke(*_, **__):
            actual = current_http_access_token()
            assert actual.subject == access.subject
            invoked.append((actual.subject, actual.claims["jti"]))
            return {"request_state": "HTTP_BOUNDARY_LAB", "subject": actual.subject}

        return OperatorBindings("/tmp/never-opened-http-lab.sqlite3", lambda _: True, invoke)

    app = server.create_operator_http_app(config=CONFIG, token_verifier=verifier, bindings_for=bindings_for)
    return SimpleNamespace(app=app, token=token, state=state, admitted=admitted, invoked=invoked)


@asynccontextmanager
async def client(boundary, *, scheme="https", remote="127.0.0.1"):
    async with (
        boundary.app.app.router.lifespan_context(boundary.app.app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=boundary.app, client=(remote, 12345)),
            base_url=scheme + "://" + CONFIG.authority,
        ) as api,
    ):
        yield api


async def rpc(api, token, method="tools/list", params=None, *, version="2025-11-25", extra_headers=None):
    headers = {
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": version,
        **(extra_headers or {}),
    }
    if token:
        headers["authorization"] = "Bearer " + token
    if version == "2026-07-28":
        headers["mcp-method"] = method
        if method == "tools/call":
            headers["mcp-name"] = params["name"]
        params = {
            **(params or {}),
            "_meta": {
                **((params or {}).get("_meta") or {}),
                "io.modelcontextprotocol/protocolVersion": version,
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        }
    return await api.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params is not None else {})},
    )


def result(response):
    assert response.status_code == 200, response.text
    return response.json()["result"]


async def test_discovery_and_401_challenge_preserve_exact_issuer_without_authenticating(boundary):
    async with client(boundary) as api:
        metadata = await api.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        assert metadata.json()["authorization_servers"] == [CONFIG.issuer]
        assert metadata.json()["resource"] == CONFIG.resource_url
        denied = await rpc(api, None)
        assert denied.status_code == 401
        assert CONFIG.metadata_url in denied.headers["www-authenticate"]
        assert (await rpc(api, "invalid")).status_code == 401
    assert not boundary.admitted and not boundary.invoked


@pytest.mark.parametrize("typ", [[], {}])
async def test_malformed_unsigned_jwt_header_returns_401_without_invocation(boundary, typ):
    parts = boundary.token().split(".")
    header = json.loads(base64.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4)))
    header["typ"] = typ
    parts[0] = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    # Deliberately do not re-sign: invalid input must fail as authentication,
    # before either an uncaught parser error or any trusted host invocation.
    async with client(boundary) as api:
        response = await rpc(api, ".".join(parts))
        assert response.status_code == 401
    assert not boundary.admitted and not boundary.invoked


@pytest.mark.parametrize("version", ["2025-11-25", "2026-07-28"])
async def test_same_server_http_discovery_advertises_only_oauth_operator(boundary, version):
    async with client(boundary) as api:
        if version == "2025-11-25":
            init = result(
                await rpc(
                    api,
                    boundary.token(),
                    "initialize",
                    {
                        "protocolVersion": version,
                        "capabilities": {},
                        "clientInfo": {"name": "isolated-http-lab", "version": "1"},
                    },
                    version=version,
                )
            )
            assert init["serverInfo"]["name"] == "trainingpeaks-mcp"
        tools = result(await rpc(api, boundary.token(), version=version))["tools"]
        assert [t["name"] for t in tools] == ["tp_ironman_request"]
        assert tools[0]["_meta"]["securitySchemes"] == [{"type": "oauth2", "scopes": [CONFIG.scope]}]
    # Existing stdio registry is not replaced or mutated by HTTP discovery.
    assert len(await server.list_tools()) > 100
    assert (server._TOOLS_BY_NAME["tp_ironman_request"].meta or {}).get("securitySchemes") is None
    assert not boundary.invoked


@pytest.mark.parametrize("version", ["2025-11-25", "2026-07-28"])
async def test_concurrent_users_and_renewed_tokens_reach_existing_handler_without_identity_leak(boundary, version):
    async with client(boundary) as api:

        async def call(subject, **claims):
            response = await rpc(
                api,
                boundary.token(subject, **claims),
                "tools/call",
                {"name": "tp_ironman_request", "arguments": COMMAND, "_meta": {"sub": "forged-human"}},
                version=version,
            )
            return json.loads(result(response)["content"][0]["text"])

        a, b = await asyncio.gather(call("human-a"), call("human-b"))
        renewed = await call("human-a", jti="access-2")
        assert [a["subject"], b["subject"], renewed["subject"]] == ["human-a", "human-b", "human-a"]
    assert sorted(boundary.invoked) == [("human-a", "access-1"), ("human-a", "access-2"), ("human-b", "access-1")]
    with pytest.raises(PermissionError):
        current_http_access_token()


async def test_http_cannot_call_legacy_tools_resources_or_inject_principal(boundary):
    async with client(boundary) as api:
        for method, params in [("tools/call", {"name": "tp_get_profile", "arguments": {}}), ("resources/list", {})]:
            response = await rpc(api, boundary.token(), method, params)
            assert response.status_code == 200 and response.json()["error"]["code"] == -32601
        denied = result(
            await rpc(
                api,
                boundary.token(),
                "tools/call",
                {"name": "tp_ironman_request", "arguments": {**COMMAND, "principal": {"sub": "human-b"}}},
            )
        )
        assert "OPERATOR_REQUEST_SHAPE" in denied["content"][0]["text"]
    assert not boundary.invoked


async def test_execution_rechecks_revocation_and_returns_oauth_linking_metadata(boundary):
    boundary.state["deny_after"] = 1
    async with client(boundary) as api:
        denied = result(
            await rpc(api, boundary.token(), "tools/call", {"name": "tp_ironman_request", "arguments": COMMAND})
        )
        assert denied["isError"] and CONFIG.metadata_url in denied["_meta"]["mcp/www_authenticate"][0]
        assert (await rpc(api, boundary.token())).status_code == 401
    assert not boundary.admitted and not boundary.invoked


async def test_missing_http_runtime_never_inherits_ambient_stdio_bindings(boundary):
    boundary.state["runtime"] = False
    ambient = []
    with bind_operator_runtime(
        OperatorBindings("/tmp/never-opened-ambient.sqlite3", lambda _: True, lambda *a, **k: ambient.append(True))
    ):
        async with client(boundary) as api:
            denied = result(
                await rpc(api, boundary.token(), "tools/call", {"name": "tp_ironman_request", "arguments": COMMAND})
            )
    assert denied["isError"] and not ambient and not boundary.invoked


@pytest.mark.parametrize("failure", ["host", "origin", "remote", "plaintext", "duplicate", "oversize", "feed"])
async def test_http_edge_and_feed_fail_closed_before_operator_invocation(boundary, failure):
    scheme, remote = (
        ("http" if failure == "plaintext" else "https"),
        ("192.0.2.1" if failure == "remote" else "127.0.0.1"),
    )
    async with client(boundary, scheme=scheme, remote=remote) as api:
        headers = {"accept": "application/json, text/event-stream", "authorization": "Bearer " + boundary.token()}
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        if failure == "host":
            headers["host"] = "untrusted.invalid"
        if failure == "origin":
            headers["origin"] = "https://untrusted.invalid"
        if failure == "feed":
            boundary.state["unavailable"] = True
        if failure == "oversize":
            body["padding"] = "x" * 2_000_000
        supplied = list(headers.items())
        if failure == "duplicate":
            supplied.append(("authorization", "Bearer another"))
        response = await api.post("/mcp", headers=supplied, json=body)
        assert response.status_code in {400, 401, 403, 413, 421}, response.text
    assert not boundary.invoked and not boundary.admitted


async def test_stdio_middleware_remains_passthrough_and_missing_host_ports_cannot_compose():
    async def next_handler(ctx):
        return "STDIO_UNCHANGED"

    assert await guard_operator_http(SimpleNamespace(request=None), next_handler) == "STDIO_UNCHANGED"
    from mcp.shared.exceptions import MCPError
    from starlette.requests import Request

    with pytest.raises(MCPError, match="Protected HTTP context required"):
        await guard_operator_http(SimpleNamespace(request=Request({"type": "http"})), next_handler)
    with pytest.raises(ValueError, match="PROTECTED_DEPENDENCIES"):
        server.create_operator_http_app(config=CONFIG, token_verifier=None, bindings_for=lambda _: None)
