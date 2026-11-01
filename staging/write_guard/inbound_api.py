"""Narrow inbound HTTP surface for IRONMAN Docs Write Guard staging.

Only a trusted operator configures credentials and scopes. ChatGPT/client requests
cannot provide provider credentials, capability registries, approval policies, or
arbitrary Google API requests. Put behind authenticated TLS transport in staging.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from authenticated_bridge import (
    SignedApprovalAuthorizer, StandingPolicy, StandingPolicyAuthorizer,
    ScopedWriteService, approval_from_mapping, make_service_account_connector,
)
from guard import Patch, GuardError, ProviderError, ExplicitSecurityDenial, ReconciliationRequired

ID_RE = r"^[A-Za-z0-9_-]{8,200}$"
OP_RE = r"^[A-Za-z0-9_.:-]{6,128}$"
HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class ReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation_id: str = Field(min_length=6, max_length=128, pattern=OP_RE)
    document_id: str = Field(min_length=8, max_length=200, pattern=ID_RE)
    expected_revision: str = Field(min_length=1, max_length=300)
    old: str = Field(min_length=1, max_length=2000)
    new: str = Field(min_length=1, max_length=5000)
    checkpoint: str = Field(min_length=4, max_length=128)
    approval_ref: str = Field(min_length=1, max_length=128)
    # No credential, URL, policy, user-provided status, generic request or registry.


@dataclass(frozen=True)
class TrustedConfig:
    actor: str
    service_account_email: str
    ledger_path: str
    bearer_token_sha256: str
    allowed_documents: frozenset[str]
    standing_policy: StandingPolicy | None = None
    # Signed approval mode requires trusted approvals and keys supplied by the
    # operator. HTTP client-supplied signed approvals are never accepted.
    signed_authorizer: SignedApprovalAuthorizer | None = None

    def validate(self) -> None:
        if not isinstance(self.actor, str) or not self.actor:
            raise ValueError("Missing trusted actor")
        if not self.service_account_email or "@" not in self.service_account_email:
            raise ValueError("Missing service account principal")
        if not HEX_RE.fullmatch(self.bearer_token_sha256):
            raise ValueError("Expected SHA-256 of independently generated bearer token")
        if not self.allowed_documents or any(not re.fullmatch(ID_RE, x) for x in self.allowed_documents):
            raise ValueError("Trusted document allowlist must be nonempty")
        if not os.path.isabs(self.ledger_path):
            raise ValueError("Ledger path must be absolute")
        if self.standing_policy is None and self.signed_authorizer is None:
            raise ValueError("No trusted authorization policy")
        if self.standing_policy is not None and self.signed_authorizer is not None:
            raise ValueError("Choose one trusted policy per runtime")
        if self.standing_policy is not None:
            p = self.standing_policy
            if p.actor != self.actor or not p.allowed_documents.issubset(self.allowed_documents):
                raise ValueError("Standing policy does not match runtime scope")


def _read_private_json(config_file: str, label: str):
    """Read trusted operator material, denying loose permissions and symlinks.

    This checks owner, regular-file type and permissions; it must be installed
    on a trusted host with a private parent directory and non-LLM-writeable
    configuration. Do not accept file paths in an inbound HTTP request.
    """
    p = Path(config_file)
    if not p.is_absolute() or p.is_symlink():
        raise ValueError(f"{label} requires absolute non-symlink path")
    metadata = p.stat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077
            or metadata.st_uid != os.geteuid()):
        raise ValueError(f"{label} requires private owner-only regular file")
    return json.loads(p.read_text(encoding="utf-8"))


def load_trusted_config(config_file: str) -> TrustedConfig:
    """Load either the bounded standing policy or independently signed grants.

    Signed keys/approvals are operator-held files; none of this material
    can be supplied by the untrusted API payload.
    """
    raw = _read_private_json(config_file, "Trusted configuration")
    base_keys = {
        "actor", "service_account_email", "ledger_path", "bearer_token_sha256",
        "allowed_documents",
    }
    if not isinstance(raw, dict) or not base_keys.issubset(raw):
        raise ValueError("Invalid trusted configuration")
    policy_keys = set(raw) - base_keys
    if policy_keys not in ({"standing_policy"}, {"signed_policy"}):
        raise ValueError("Choose exactly one trusted authorization policy")
    kwargs = {}
    if "standing_policy" in raw:
        policy_raw = raw["standing_policy"]
        if not isinstance(policy_raw, dict) or set(policy_raw) != {
            "policy_id", "actor", "allowed_documents", "expires_at", "max_replacement_chars"
        }:
            raise ValueError("Invalid trusted standing policy")
        kwargs["standing_policy"] = StandingPolicy(
            policy_id=policy_raw["policy_id"], actor=policy_raw["actor"],
            allowed_documents=frozenset(policy_raw["allowed_documents"]),
            expires_at=policy_raw["expires_at"],
            max_replacement_chars=policy_raw["max_replacement_chars"],
        )
    else:
        signed = raw["signed_policy"]
        if not isinstance(signed, dict) or set(signed) != {"keys_file", "approvals_file"}:
            raise ValueError("Invalid trusted signed policy")
        key_map = _read_private_json(signed["keys_file"], "Signing keys")
        approval_list = _read_private_json(signed["approvals_file"], "Signed approvals")
        if not isinstance(key_map, dict) or not key_map:
            raise ValueError("Invalid trusted signing keys")
        keys = {}
        for k, v in key_map.items():
            if not isinstance(k, str) or not k or not isinstance(v, str):
                raise ValueError("Invalid signing key entry")
            try:
                decoded = bytes.fromhex(v)
            except ValueError:
                raise ValueError("Invalid signing key encoding") from None
            if len(decoded) < 32:
                raise ValueError("Signing keys must contain at least 32 bytes")
            keys[k] = decoded
        if not isinstance(approval_list, list):
            raise ValueError("Invalid signed approvals list")
        approvals = {}
        for entry in approval_list:
            a = approval_from_mapping(entry)
            if a.approval_ref in approvals:
                raise ValueError("Duplicate signed approval reference")
            approvals[a.approval_ref] = a
        kwargs["signed_authorizer"] = SignedApprovalAuthorizer(
            actor=raw["actor"], trusted_approvals=approvals, trusted_keys=keys,
        )
    cfg = TrustedConfig(
        actor=raw["actor"], service_account_email=raw["service_account_email"],
        ledger_path=raw["ledger_path"],
        bearer_token_sha256=raw["bearer_token_sha256"],
        allowed_documents=frozenset(raw["allowed_documents"]), **kwargs,
    )
    cfg.validate()
    return cfg


def build_app(config: TrustedConfig, service_factory: Callable[[], ScopedWriteService]) -> FastAPI:
    """Create inbound service; call service_factory only after caller auth.

    The HTTP app is not itself an MCP server. Its API can be wrapped by a
    reviewed/approved ChatGPT connector only after the staging deployment.
    """
    config.validate()
    app = FastAPI(title="IRONMAN Write Guard staging", docs_url=None, redoc_url=None, openapi_url=None)

    def authenticate(authorization: str | None = Header(default=None)) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = authorization[len("Bearer "):]
        # Upper bound prevents indefinite computation on bogus requests.
        if not 32 <= len(token) <= 512 or not hmac.compare_digest(
            hashlib.sha256(token.encode("utf-8")).hexdigest(), config.bearer_token_sha256
        ):
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/health/live")
    def live():
        return {"state": "running"}  # Does not attest provider/Docs readiness.

    @app.get("/v1/operations/{operation_id}", dependencies=[Depends(authenticate)])
    def operation_state(operation_id: str):
        if not re.fullmatch(OP_RE, operation_id):
            raise HTTPException(status_code=422, detail="Invalid operation identifier")
        try:
            with sqlite3.connect(config.ledger_path, timeout=10) as db:
                row = db.execute(
                    "SELECT document_id, state FROM operations WHERE operation_id=?", (operation_id,)
                ).fetchone()
        except sqlite3.Error:
            raise HTTPException(status_code=503, detail="Ledger temporarily unavailable")
        if row is None or row[0] not in config.allowed_documents:
            raise HTTPException(status_code=404, detail="Operation not found")
        return {"operation_id": operation_id, "status": row[1]}

    @app.post("/v1/docs/replace", dependencies=[Depends(authenticate)])
    def replace(payload: ReplaceRequest):
        if payload.document_id not in config.allowed_documents:
            raise HTTPException(status_code=403, detail="Document not authorized for this service")
        patch = Patch(
            operation_id=payload.operation_id, document_id=payload.document_id,
            proven_path="AUTO", expected_revision=payload.expected_revision,
            old=payload.old, new=payload.new, checkpoint=payload.checkpoint,
            approval_ref=payload.approval_ref,
        )
        try:
            status = service_factory().execute(patch)
            return {"operation_id":patch.operation_id, "status":status}
        except ExplicitSecurityDenial:
            raise HTTPException(status_code=403, detail="Provider denied this operation")
        except ReconciliationRequired:
            raise HTTPException(status_code=409, detail="Reconciliation required; no automatic replay")
        except GuardError as exc:
            msg = str(exc)
            if "Stale revision" in msg or "collision" in msg or "Checkpoint present" in msg:
                raise HTTPException(status_code=409, detail="Operation conflicts with current state")
            if "Authorization" in msg or "allowlist" in msg or "Prior explicit" in msg:
                raise HTTPException(status_code=403, detail="Operation not authorized")
            if isinstance(exc, ProviderError):
                raise HTTPException(status_code=502, detail="Provider operation did not verify")
            raise HTTPException(status_code=422, detail="Operation failed contract validation")
        except Exception:
            # Avoid exposing provider responses, token material, filenames, or stack traces.
            raise HTTPException(status_code=503, detail="Service temporarily unavailable")
    return app


def create_runtime_app() -> FastAPI:
    filename = os.environ.get("WG_CONFIG_PATH")
    if not filename:
        raise RuntimeError("WG_CONFIG_PATH must reference operator-owned private configuration")
    cfg = load_trusted_config(filename)
    def build_service():
        authorizer = cfg.signed_authorizer or StandingPolicyAuthorizer(actor=cfg.actor, policy=cfg.standing_policy)
        return ScopedWriteService(
            connector=make_service_account_connector(expected_email=cfg.service_account_email),
            authorizer=authorizer,
            ledger_path=cfg.ledger_path,
            allowed_documents=set(cfg.allowed_documents),
        )
    return build_app(cfg, build_service)
