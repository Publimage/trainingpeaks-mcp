"""Reviewed integration boundary between DocsWriteGuard and the Google Docs API.

The bridge requires a server-held approval signing key and Google ADC credentials
for a dedicated service account. Neither an LLM-supplied token nor a capability
label grants permission. No credentials or production settings ship with this POC.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote

from guard import DocsWriteGuard, Patch, GuardError, ProviderError, ExplicitSecurityDenial
from google_docs_adapter import GoogleDocsConnectorAdapter

DOCS_SCOPE = "https://www.googleapis.com/auth/documents"
DOCS_API_ORIGIN = "https://docs.googleapis.com/v1/documents"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,200}$")


class HttpSession(Protocol):
    def get(self, url: str, *, params: dict, timeout: float): ...
    def post(self, url: str, *, json: dict, timeout: float): ...


class GoogleDocsRestConnector:
    """HTTP bridge using only approved Google Docs URLs (no arbitrary URL target).

    The injected session MUST be an AuthorizedSession or a deterministic test fake.
    Never expose session construction or credentials to untrusted operation data.
    """
    def __init__(self, session: HttpSession, *, timeout_seconds: float = 15):
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("Timeout outside supported range")
        self._session = session
        self._timeout = timeout_seconds

    @staticmethod
    def _url(document_id: str) -> str:
        if not isinstance(document_id, str) or not ID_PATTERN.fullmatch(document_id):
            raise ProviderError("Invalid document identifier")
        return f"{DOCS_API_ORIGIN}/{quote(document_id, safe='')}"

    @staticmethod
    def _json(response) -> dict:
        # Provider HTTP 403 is an explicit permission denial for this call.
        # 401 can indicate expired authentication and is not treated as permanent.
        # No retries or changed routes are attempted here.
        if getattr(response, "status_code", None) == 403:
            raise ExplicitSecurityDenial("Google Docs explicitly denied access to this operation")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ProviderError("Non-object Google Docs response")
        return payload

    def get_document(self, *, document_id: str, fields: str) -> dict:
        if fields != GoogleDocsConnectorAdapter.FIELDS:
            raise ProviderError("Unapproved Docs read fields")
        return self._json(self._session.get(
            self._url(document_id), params={"includeTabsContent": "true", "fields": fields},
            timeout=self._timeout,
        ))

    def batch_update_document(self, *, document_id: str, requests: list[dict],
                              write_control: dict) -> dict:
        if not isinstance(requests, list) or len(requests) != 1:
            raise ProviderError("Exactly one tab-scoped replacement required")
        req = requests[0]
        obj = req.get("replaceAllText") if isinstance(req, dict) else None
        if not isinstance(obj, dict) or set(obj) != {"containsText", "replaceText", "tabsCriteria"}:
            raise ProviderError("Unapproved Docs mutation shape")
        if not isinstance(obj["containsText"], dict) or set(obj["containsText"]) != {"text", "matchCase"} or obj["containsText"]["matchCase"] is not True:
            raise ProviderError("Exact-case replacement mandatory")
        if not isinstance(obj["tabsCriteria"], dict):
            raise ProviderError("Invalid tab scope")
        tabs = obj["tabsCriteria"].get("tabIds", [])
        if not isinstance(tabs, list) or len(tabs) != 1 or not isinstance(tabs[0], str):
            raise ProviderError("One explicit tab ID mandatory")
        if not isinstance(write_control, dict) or set(write_control) != {"requiredRevisionId"} or not isinstance(write_control["requiredRevisionId"], str) or not write_control["requiredRevisionId"]:
            raise ProviderError("requiredRevisionId mandatory")
        return self._json(self._session.post(
            self._url(document_id) + ":batchUpdate",
            json={"requests": requests, "writeControl": write_control},
            timeout=self._timeout,
        ))


def make_service_account_connector(*, expected_email: str, timeout_seconds: float = 15) -> GoogleDocsRestConnector:
    """Construct a real authenticated connector only in a trusted runtime.

    Requires installed google-auth and ADC of a dedicated service account with
    access only to explicitly shared test/prod Docs. For other credential types,
    introduce a reviewed workload identity verification strategy separately.
    """
    if not expected_email or "@" not in expected_email:
        raise GuardError("Expected service identity must be configured")
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.service_account import Credentials as ServiceAccountCredentials
    except ImportError as exc:
        raise RuntimeError("Runtime requires google-auth; see requirements-runtime.txt") from exc
    credentials, _ = google.auth.default(scopes=[DOCS_SCOPE])
    if not isinstance(credentials, ServiceAccountCredentials):
        raise GuardError("Dedicated service-account ADC required; user token not accepted")
    if credentials.service_account_email != expected_email:
        raise GuardError("Service account principal does not match server configuration")
    return GoogleDocsRestConnector(AuthorizedSession(credentials), timeout_seconds=timeout_seconds)


@dataclass(frozen=True)
class SignedApproval:
    approval_ref: str
    patch_digest: str
    actor: str
    expires_at: str
    key_id: str
    signature: str

    def signed_body(self) -> bytes:
        return json.dumps({
            "actor": self.actor, "approval_ref": self.approval_ref,
            "expires_at": self.expires_at, "key_id": self.key_id,
            "patch_digest": self.patch_digest,
        }, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class SignedApprovalAuthorizer:
    """Authorizations are independently issued and cryptographically bound.

    Approvals and signing keys are provisioned by the trusted service operator,
    *not* through user/assistant editable source documents or work requests.
    """
    def __init__(self, *, actor: str, trusted_approvals: dict[str, SignedApproval],
                 trusted_keys: dict[str, bytes], now=None):
        self.actor = actor
        self._approvals = dict(trusted_approvals)
        self._keys = dict(trusted_keys)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def permits(self, patch: Patch) -> bool:
        grant = self._approvals.get(patch.approval_ref)
        if grant is None or grant.approval_ref != patch.approval_ref:
            return False
        key = self._keys.get(grant.key_id)
        if not isinstance(key, bytes) or len(key) < 32:
            return False
        if grant.actor != self.actor or grant.patch_digest != patch.digest():
            return False
        try:
            expiry = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None or self._now() >= expiry:
                return False
        except (ValueError, TypeError):
            return False
        expect = hmac.new(key, grant.signed_body(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expect, grant.signature)


@dataclass(frozen=True)
class StandingPolicy:
    """Server-owner-approved limited scope; never constructed from a chat payload."""
    policy_id: str
    actor: str
    allowed_documents: frozenset[str]
    expires_at: str
    max_replacement_chars: int = 1600


class StandingPolicyAuthorizer:
    """Allows low-impact checkpoints without requiring a new grant per document.

    The policy must be loaded by a trusted server from independently approved
    configuration. Never trust policy fields supplied in the API write request.
    """
    def __init__(self, *, actor: str, policy: StandingPolicy, now=None):
        self.actor = actor
        self.policy = policy
        self._now = now or (lambda: datetime.now(timezone.utc))

    def permits(self, patch: Patch) -> bool:
        p = self.policy
        if patch.approval_ref != p.policy_id or p.actor != self.actor:
            return False
        if patch.document_id not in p.allowed_documents or patch.proven_path not in ('AUTO', 'DRIVE-DOC-004', 'KB-DOCS-RELIABLE-WRITE-033'):
            return False
        try:
            expiry = datetime.fromisoformat(p.expires_at.replace('Z', '+00:00'))
            if expiry.tzinfo is None or self._now() >= expiry:
                return False
        except (TypeError, ValueError):
            return False
        # This standing authorization permits bounded checkpoint replacement,
        # NOT arbitrary document rewriting or content deletion.
        if len(patch.new) > p.max_replacement_chars or len(patch.old) > 400:
            return False
        if patch.old not in patch.new or patch.new.count(patch.old) != 1:
            return False
        if not patch.checkpoint.startswith('IRONMAN_') or len(patch.checkpoint) > 128:
            return False
        if patch.new.count(patch.checkpoint) != 1:
            return False
        return True


class ScopedWriteService:
    """Single guarded write entrypoint; no generic Docs write function exposed."""
    def __init__(self, *, connector: GoogleDocsRestConnector,
                 authorizer: SignedApprovalAuthorizer | StandingPolicyAuthorizer,
                 ledger_path: str, allowed_documents: set[str], tab_id: str = "t.0"):
        if not allowed_documents or not all(ID_PATTERN.fullmatch(x) for x in allowed_documents):
            raise GuardError("Server-side allowlist required")
        self._guard = DocsWriteGuard(
            GoogleDocsConnectorAdapter(connector, tab_id=tab_id), authorizer,
            ledger_path, allowed_documents,
        )

    def execute(self, patch: Patch) -> str:
        return self._guard.execute(patch)


def approval_from_mapping(value: dict[str, Any]) -> SignedApproval:
    keys = {"approval_ref", "patch_digest", "actor", "expires_at", "key_id", "signature"}
    if set(value) != keys or not all(isinstance(value[k], str) for k in keys):
        raise ValueError("Invalid signed approval record")
    return SignedApproval(**value)
