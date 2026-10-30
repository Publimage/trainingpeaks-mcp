"""Opt-in HTTP transport for the existing operator; never opens a listener.

The host supplies protected configuration, an OAuth/revocation verifier and its
existing binding factory. Default stdio startup installs none of them. HTTP has
no session authority: every exchange authenticates independently; durable
operation state and retry identity remain in the existing operator/Prefect path.
"""

from __future__ import annotations

import ipaddress
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import AccessToken, TokenVerifier, principal_components
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, TextContent
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from tp_mcp.operator_runtime import OperatorBindings, bind_operator_runtime

_OPERATOR = "tp_ironman_request"


@dataclass(frozen=True)
class OperatorHTTPConfig:
    resource_url: str
    issuer: str
    scope: str
    local_host: str
    local_port: int

    def __post_init__(self) -> None:
        for value in (self.resource_url, self.issuer):
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or any(c.isspace() for c in value)
            ):
                raise ValueError("OPERATOR_HTTP_HTTPS_TRUST_REQUIRED")
        if (
            not ipaddress.ip_address(self.local_host).is_loopback
            or type(self.local_port) is not int
            or not 1 <= self.local_port <= 65535
            or not self.scope
            or any(c.isspace() or c in '"\\' for c in self.scope)
        ):
            raise ValueError("OPERATOR_HTTP_LOCAL_CONFIGURATION_REQUIRED")

    @property
    def authority(self) -> str:
        host = f"[{self.local_host}]" if ":" in self.local_host else self.local_host
        return f"{host}:{self.local_port}"

    @property
    def metadata_url(self) -> str:
        return str(build_resource_metadata_url(AnyHttpUrl(self.resource_url)))


class _BoundVerifier:
    def __init__(self, verifier: TokenVerifier, config: OperatorHTTPConfig):
        self.verifier, self.config = verifier, config

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            verified = await self.verifier.verify_token(token)
            if (
                not isinstance(verified, AccessToken)
                or not verified.subject
                or not verified.client_id
                or (verified.claims or {}).get("iss") != self.config.issuer
                or verified.resource != self.config.resource_url
                or self.config.scope not in verified.scopes
                or verified.expires_at is None
                or verified.expires_at <= time.time()
            ):
                return None
            return verified
        except (PermissionError, OSError, ValueError):
            return None


@dataclass(frozen=True)
class _HTTPRequest:
    token: AccessToken
    verifier: _BoundVerifier
    bindings_for: Callable[[AccessToken], OperatorBindings | None]
    config: OperatorHTTPConfig


_http_request: ContextVar[_HTTPRequest | None] = ContextVar("operator_http_request", default=None)


def current_http_access_token() -> AccessToken:
    """Trusted host code only; never obtained from tool arguments/JSON-RPC meta."""
    request = _http_request.get()
    if request is None:
        raise PermissionError("OPERATOR_HTTP_IDENTITY_REQUIRED")
    return request.token


async def guard_operator_http(ctx: Any, call_next: Any) -> Any:
    """SDK context middleware on the ONE server; stdio follows its existing path."""
    request = _http_request.get()
    if request is None:
        if isinstance(ctx.request, Request):
            raise MCPError(code=-32600, message="Protected HTTP context required")
        return await call_next(ctx)
    if ctx.method in {"initialize", "notifications/initialized", "ping"}:
        return await call_next(ctx)
    if ctx.method == "tools/list":
        result = await call_next(ctx)
        schemes = [{"type": "oauth2", "scopes": [request.config.scope]}]
        return {
            **result,
            "tools": [
                {**tool, "securitySchemes": schemes, "_meta": {**(tool.get("_meta") or {}), "securitySchemes": schemes}}
                for tool in result["tools"]
                if tool["name"] == _OPERATOR
            ],
        }
    if ctx.method != "tools/call" or (ctx.params or {}).get("name") != _OPERATOR:
        raise MCPError(code=-32601, message="Method unavailable on operator HTTP ingress")
    # Revalidate at execution, not just at HTTP admission: SDK dispatch may wait.
    token = await request.verifier.verify_token(request.token.token)
    if token is None or principal_components(token) != principal_components(request.token):
        return CallToolResult(
            is_error=True,
            content=[TextContent(type="text", text="OPERATOR_HTTP_AUTH_REQUIRED")],
            _meta={"mcp/www_authenticate": [f'Bearer resource_metadata="{request.config.metadata_url}"']},
        )
    runtime = request.bindings_for(token)
    if not isinstance(runtime, OperatorBindings):
        return CallToolResult(is_error=True, content=[TextContent(type="text", text="OPERATOR_RUNTIME_NOT_CONFIGURED")])
    with bind_operator_runtime(runtime):
        return await call_next(ctx)


class _HTTPRequestContext:
    def __init__(
        self,
        app: ASGIApp,
        request_verifier: _BoundVerifier,
        bindings_for: Callable[[AccessToken], OperatorBindings | None],
        config: OperatorHTTPConfig,
    ):
        self.app, self.verifier, self.bindings_for, self.config = app, request_verifier, bindings_for, config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Reached only after SDK Authentication/RequireAuth middleware.
        user = scope["user"]
        token = _http_request.set(_HTTPRequest(user.access_token, self.verifier, self.bindings_for, self.config))
        try:
            await self.app(scope, receive, send)
        finally:
            _http_request.reset(token)


class _HTTPBoundary:
    def __init__(self, app: ASGIApp, settings: TransportSecuritySettings):
        self.app = app
        self.security = TransportSecurityMiddleware(settings)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        remote = scope.get("client") or ("", 0)
        try:
            local = ipaddress.ip_address(remote[0]).is_loopback
        except ValueError:
            local = False
        if not local or scope.get("scheme") != "https":
            await JSONResponse({"error": "OPERATOR_HTTP_LOCAL_TLS_REQUIRED"}, status_code=403)(scope, receive, send)
            return
        invalid = await self.security.validate_request(request, is_post=scope["method"] == "POST")
        if invalid is not None:
            await invalid(scope, receive, send)
            return
        if len(request.headers.getlist("authorization")) > 1:
            await JSONResponse({"error": "AMBIGUOUS_AUTHORIZATION"}, status_code=400)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_operator_http_app(
    server: Any,
    *,
    config: OperatorHTTPConfig,
    token_verifier: TokenVerifier,
    bindings_for: Callable[[AccessToken], OperatorBindings | None],
) -> ASGIApp:
    """Compose the existing SDK server. No env fallback, bind, launch or issuer."""
    if (
        not isinstance(config, OperatorHTTPConfig)
        or not callable(getattr(token_verifier, "verify_token", None))
        or not callable(bindings_for)
        or guard_operator_http not in server.middleware
    ):
        raise ValueError("OPERATOR_HTTP_PROTECTED_DEPENDENCIES_REQUIRED")
    verifier = _BoundVerifier(token_verifier, config)
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[config.authority],
        allowed_origins=["https://" + config.authority],
    )
    manager = StreamableHTTPSessionManager(
        server,
        stateless=True,
        json_response=True,
        max_request_body_size=2_000_000,
        security_settings=security,
    )

    @asynccontextmanager
    async def lifespan(app: Starlette):
        async with manager.run():
            yield

    async def metadata(request: Request) -> JSONResponse:
        # Keep exact configured issuer spelling: URL coercion can add a slash
        # that breaks OAuth's exact issuer comparison. No AS/proxy is created.
        return JSONResponse(
            {
                "resource": config.resource_url,
                "authorization_servers": [config.issuer],
                "scopes_supported": [config.scope],
                "bearer_methods_supported": ["header"],
            }
        )

    protected = AuthenticationMiddleware(
        RequireAuthMiddleware(
            _HTTPRequestContext(manager.asgi_app, verifier, bindings_for, config),
            required_scopes=[config.scope],
            resource_metadata_url=AnyHttpUrl(config.metadata_url),
        ),
        backend=BearerAuthBackend(verifier),
    )
    routes = [
        Route("/mcp", endpoint=protected, methods=["POST", "GET", "DELETE"]),
        Route(urlsplit(config.metadata_url).path, endpoint=metadata, methods=["GET"]),
    ]
    return _HTTPBoundary(Starlette(routes=routes, lifespan=lifespan), security)
