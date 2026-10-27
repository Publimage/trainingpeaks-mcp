"""Host-local signed identity, exact request grants, revocation and audit.

No issuer, private signing key, network endpoint or provider credential is
created here. The existing host supplies public trust configuration and an
assertion from its authenticated issuer, outside serialized flow parameters.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

from scripts.ironman_jobs.ironman_dynamic_request_store import DraftStore, canonical
from scripts.ironman_jobs.ironman_local_state import require_private_path
from scripts.ironman_jobs.ironman_unified_changeset_engine import digest

ACTIONS = frozenset({"approve_preview", "bind_execution", "revoke_approval",
                     "execute_change", "recover_worker"})
BINDING_FIELDS = ("issuer", "subject", "request_id", "preview_sha256",
                  "reviewed_revision", "approval_scope", "manifest_sha256")


def require(ok: bool, code: str) -> None:
    if not ok:
        raise PermissionError(code)


def _json(raw: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise PermissionError("INVALID_AUTH_JSON") from exc


def read_host_file(path: Path, limit: int) -> bytes:
    """Bounded, private host input. Never follow a request-selected URL/path."""
    path = Path(path)
    require_private_path(path)
    require(type(limit) is int and limit > 0, "INVALID_AUTH_FILE_LIMIT")
    try:
        # A malformed host input must not hang a Prefect worker waiting for a
        # FIFO writer. O_NOFOLLOW also protects the final path at open time.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise PermissionError("UNSAFE_AUTH_FILE") from exc
    try:
        meta = os.fstat(fd)
        require(stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1 and
                meta.st_uid in {0, os.geteuid()} and not meta.st_mode & 0o077 and
                meta.st_size <= limit, "UNSAFE_AUTH_FILE")
        raw = b""
        while len(raw) <= limit:
            chunk = os.read(fd, limit + 1 - len(raw))
            if not chunk:
                break
            raw += chunk
        require(len(raw) <= limit, "AUTH_FILE_TOO_LARGE")
        # Reject replacement or in-place edits during a read; a subsequent
        # invocation may consume a completed rotation, never a mixed snapshot.
        def version(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                    info.st_ctime_ns, info.st_mode, info.st_uid, info.st_nlink)
        require_private_path(path)
        require(version(meta) == version(os.fstat(fd)) == version(path.lstat()) and
                len(raw) == meta.st_size, "AUTH_FILE_CHANGED_DURING_READ")
        return raw
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str
    token_id: str
    expires_at: int
    invocation_id: str


class SignedIdentityVerifier:
    """Strict compact JWT verifier using pinned public keys, never token URLs.

    Algorithm and key type are pinned in host trust config. Both RS256 and
    EdDSA use the repository's existing cryptography dependency.
    """
    def __init__(self, config: dict, clock: Callable[[], float] = time.time):
        require(type(config) is dict and set(config) == {"issuer", "audience", "required_scope", "keys", "administrators"},
                "AUTH_TRUST_CONFIG")
        require(all(type(config[k]) is str and config[k] for k in ("issuer", "audience", "required_scope")) and
                type(config["keys"]) is dict and 0 < len(config["keys"]) <= 16, "AUTH_TRUST_CONFIG")
        self.issuer, self.audience, self.scope = (config[k] for k in ("issuer", "audience", "required_scope"))
        require(type(config["administrators"]) is list and
                all(type(s) is str and 0 < len(s) <= 256 for s in config["administrators"]), "AUTH_ADMIN_CONFIG")
        self.administrators = frozenset(config["administrators"])
        self.keys, self.clock = {}, clock
        for kid, entry in config["keys"].items():
            require(type(kid) is str and 0 < len(kid) <= 120 and type(entry) is dict and
                    set(entry) == {"algorithm", "public_key_pem"}, "AUTH_TRUST_KEY")
            key = serialization.load_pem_public_key(entry["public_key_pem"].encode())
            alg = entry["algorithm"]
            require((alg == "EdDSA" and isinstance(key, ed25519.Ed25519PublicKey)) or
                    (alg == "RS256" and isinstance(key, rsa.RSAPublicKey) and key.key_size >= 2048),
                    "AUTH_TRUST_ALGORITHM")
            self.keys[kid] = (alg, key)

    def verify(self, token: str) -> Principal:
        require(type(token) is str and 0 < len(token) <= 32768, "INVALID_ASSERTION")
        parts = token.split(".")
        require(len(parts) == 3, "INVALID_ASSERTION")

        def decode(part):
            require(re.fullmatch(r"[A-Za-z0-9_-]+", part) is not None, "INVALID_ASSERTION")
            try:
                raw = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
            except ValueError as exc:
                raise PermissionError("INVALID_ASSERTION") from exc
            require(base64.urlsafe_b64encode(raw).decode().rstrip("=") == part, "INVALID_ASSERTION")
            return raw

        header, claims, signature = _json(decode(parts[0])), _json(decode(parts[1])), decode(parts[2])
        require(type(header) is dict and set(header) in ({"kid", "alg"}, {"kid", "alg", "typ"}) and
                header.get("typ", "JWT") in {"JWT", "at+jwt"} and
                type(header.get("kid")) is str and header["kid"] in self.keys, "INVALID_ASSERTION_HEADER")
        alg, key = self.keys[header["kid"]]
        require(header.get("alg") == alg, "ASSERTION_ALGORITHM_MISMATCH")
        signed = (parts[0] + "." + parts[1]).encode("ascii")
        try:
            if alg == "RS256" and isinstance(key, rsa.RSAPublicKey):
                key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
            elif alg == "EdDSA" and isinstance(key, ed25519.Ed25519PublicKey):
                key.verify(signature, signed)
            else:
                raise PermissionError("ASSERTION_ALGORITHM_MISMATCH")
        except (InvalidSignature, ValueError) as exc:
            raise PermissionError("ASSERTION_SIGNATURE_INVALID") from exc
        require(type(claims) is dict and all(type(claims.get(k)) is int for k in ("iat", "nbf", "exp")),
                "ASSERTION_TIME_REQUIRED")
        now = self.clock()
        require(claims["iat"] <= now and claims["nbf"] <= now < claims["exp"] and
                claims["iat"] < claims["exp"], "ASSERTION_EXPIRED_OR_NOT_CURRENT")
        audiences = claims.get("aud")
        audiences = [audiences] if type(audiences) is str else audiences
        require(claims.get("iss") == self.issuer and type(audiences) is list and
                all(type(x) is str for x in audiences) and self.audience in audiences,
                "ASSERTION_ISSUER_OR_AUDIENCE")
        require(all(type(claims.get(k)) is str and 0 < len(claims[k]) <= 256 for k in ("sub", "jti", "run_id")),
                "ASSERTION_PRINCIPAL_REQUIRED")
        require(type(claims.get("scope")) is str and self.scope in claims["scope"].split(),
                "ASSERTION_SCOPE_REQUIRED")
        return Principal(self.issuer, claims["sub"], claims["jti"], claims["exp"], claims["run_id"])


def current_invocation_id() -> str:
    """Trusted scheduler context, never a flow argument or environment override."""
    try:
        from prefect.context import get_run_context
        context = get_run_context()
        # Prefect's task context carries the parent flow reference on the
        # task-run model, not a flow_run object. Never substitute task_run.id:
        # the signed delegation belongs to the originating flow invocation.
        flow = getattr(context, "flow_run", None)
        task = getattr(context, "task_run", None)
        origins = {str(value) for value in (
            getattr(flow, "id", None), getattr(task, "flow_run_id", None)
        ) if value is not None and str(value)}
        require(len(origins) == 1 and "None" not in origins, "INVOCATION_ID_REQUIRED")
        return origins.pop()
    except (ImportError, AttributeError, RuntimeError) as exc:
        raise PermissionError("AUTHENTICATED_INVOCATION_REQUIRED") from exc


class HostReviewAuthority:
    """Concrete authority over the EXISTING DraftStore database.

    Grant/revoke methods are trusted host administration primitives, never flow
    inputs or MCP tools. Nothing automatically grants the caller a permission.
    """
    def __init__(self, store_path: Path, verifier: SignedIdentityVerifier,
                 assertion_reader: Callable[[], str], clock: Callable[[], float] = time.time,
                 invocation_id_provider: Callable[[], str] = current_invocation_id):
        self.path, self.verifier, self.assertion_reader, self.clock = Path(store_path), verifier, assertion_reader, clock
        self.invocation_id_provider = invocation_id_provider

    def _identity(self):
        principal = self.verifier.verify(self.assertion_reader())
        require(principal.invocation_id == self.invocation_id_provider(), "ASSERTION_INVOCATION_MISMATCH")
        return principal

    def _store(self):
        store = DraftStore(self.path)
        self._ensure_tables(store)
        return store

    @staticmethod
    def _ensure_tables(store):
        store.verify_storage()
        store.db.executescript("""
            CREATE TABLE IF NOT EXISTS authority_grants (
                grant_id TEXT PRIMARY KEY, binding_sha TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS authority_grants_binding ON authority_grants(binding_sha);
            CREATE TABLE IF NOT EXISTS authority_revocations (
                kind TEXT NOT NULL, identity TEXT NOT NULL, PRIMARY KEY(kind,identity));
            CREATE TABLE IF NOT EXISTS authority_audit (
                sequence INTEGER PRIMARY KEY, observed_at REAL NOT NULL,
                issuer TEXT, subject TEXT, request_id TEXT, action TEXT,
                command_sha TEXT NOT NULL, allowed INTEGER NOT NULL, code TEXT NOT NULL);
        """)

    @staticmethod
    def _revoked(store, kind, identity):
        return store.db.execute("SELECT 1 FROM authority_revocations WHERE kind=? AND identity=?",
                                (kind, identity)).fetchone() is not None

    def _admin(self, store):
        principal = self._identity()
        require(principal.subject in self.verifier.administrators and
                not self._revoked(store, "principal", canonical([principal.issuer, principal.subject])) and
                not self._revoked(store, "token", canonical([principal.issuer, principal.token_id])),
                "AUTHORITY_ADMIN_REQUIRED")
        return principal

    def _audit(self, store, principal, request_id, action, command, allowed, code):
        store.db.execute("""INSERT INTO authority_audit
            (observed_at,issuer,subject,request_id,action,command_sha,allowed,code)
            VALUES (?,?,?,?,?,?,?,?)""", (
                self.clock(), principal.issuer if principal else None,
                principal.subject if principal else None, request_id, action,
                digest(command), int(allowed), code))

    def grant(self, principal: Principal, request_id: str, preview_sha: str, *,
              approval_scope: str, actions: list[str], expires_at: int) -> str:
        """Trusted host issues an immutable exact-preview grant after review."""
        require(type(expires_at) is int and self.clock() < expires_at <= principal.expires_at and
                type(actions) is list and actions and all(type(a) is str and a in ACTIONS for a in actions) and
                len(set(actions)) == len(actions), "INVALID_GRANT")
        store = self._store()
        try:
            store.db.execute("BEGIN IMMEDIATE")
            admin = self._admin(store)
            require(principal.issuer == self.verifier.issuer, "GRANT_ISSUER_MISMATCH")
            snapshot = store.get_preview(request_id, preview_sha)
            require(snapshot is not None, "PREVIEW_VERSION_NOT_FOUND")
            # Reuse the review's revision/scope validation without recording an approval.
            m = snapshot["manifest"]
            store._approval_record(request_id, preview_sha, approved_revision=m["reviewed_revision"],
                                   approval_scope=approval_scope, requested_targets=list({
                                       canonical({"kind": c["kind"], "target": c["target"]}):
                                       {"kind": c["kind"], "target": c["target"]} for c in m["changes"]}.values()))
            record = dict(issuer=principal.issuer, subject=principal.subject, request_id=request_id,
                          preview_sha256=preview_sha, reviewed_revision=m["reviewed_revision"],
                          approval_scope=approval_scope, manifest_sha256=digest(m),
                          actions=sorted(actions), expires_at=expires_at, granted_by=admin.subject)
            grant_id = digest(record)
            binding_sha = digest([record[k] for k in BINDING_FIELDS])
            require(not self._revoked(store, "grant", grant_id), "GRANT_REVOKED")
            existing = store.db.execute("SELECT binding_sha,payload FROM authority_grants WHERE grant_id=?",
                                         (grant_id,)).fetchone()
            require(existing is None or existing == (binding_sha, canonical(record)), "GRANT_RECORD_CORRUPT")
            store.db.execute("INSERT OR IGNORE INTO authority_grants VALUES (?,?,?)",
                             (grant_id, binding_sha, canonical(record)))
            self._audit(store, admin, request_id, "grant", record, True, "GRANT_RECORDED")
            store.db.commit()
            return grant_id
        except Exception:
            store.db.rollback()
            raise
        finally:
            store.close()

    def revoke(self, kind: str, identity: str) -> None:
        require(kind in {"grant", "token", "principal"} and type(identity) is str and bool(identity), "INVALID_REVOCATION")
        store = self._store()
        try:
            store.db.execute("BEGIN IMMEDIATE")
            admin = self._admin(store)
            store.db.execute("INSERT OR IGNORE INTO authority_revocations VALUES (?,?)", (kind, identity))
            self._audit(store, admin, None, "revoke", {"kind": kind, "identity": identity}, True, "REVOKED")
            store.db.commit()
        except Exception:
            store.db.rollback()
            raise
        finally:
            store.close()

    def authorize(self, command: dict) -> bool:
        principal, allowed, code = None, False, "AUTHORIZATION_DENIED"
        try:
            principal = self._identity()
        except (PermissionError, OSError, ValueError, TypeError):
            code = "IDENTITY_UNVERIFIED"
        store = self._store()
        try:
            store.db.execute("BEGIN IMMEDIATE")
            try:
                if principal is not None:
                    allowed = self._authorize_locked(store, principal, command)
                    code = "AUTHORIZED" if allowed else "GRANT_MISSING_EXPIRED_OR_REVOKED"
            except (KeyError, ValueError, TypeError, PermissionError):
                allowed, code = False, "COMMAND_BINDING_INVALID"
            review = command.get("review", {}) if type(command) is dict else {}
            request_id = command.get("request_id", review.get("request_id"))
            self._audit(store, principal, request_id, command.get("action"), command, allowed, code)
            store.db.commit()
            return allowed
        except Exception:
            store.db.rollback()
            raise
        finally:
            store.close()

    def run_control(self, command: dict, store: DraftStore) -> dict:
        """Authorize and mutate on the SAME SQLite connection/transaction.

        Concurrent grant revocation is serialized with recording approval or
        binding. A post-check grant revocation cannot slip between these steps.
        """
        from scripts.ironman_jobs.ironman_operation_contracts import apply_review_control
        require(store.path.resolve() == self.path.resolve() and not store.db.in_transaction,
                "AUTHORITY_STORE_MISMATCH")
        require(command.get("action") in {"approve_preview", "bind_execution", "revoke_approval"},
                "UNSUPPORTED_REVIEW_CONTROL")
        self._ensure_tables(store)
        principal = None
        with store.write_transaction():
            try:
                principal = self._identity()
                require(self._authorize_locked(store, principal, command), "REVIEW_AUTHORIZATION_DENIED")
                with store.write_transaction():
                    result = apply_review_control(store, command)
            except (PermissionError, OSError, ValueError, TypeError) as exc:
                error = exc
                self._audit(store, principal, command["review"].get("request_id"), command["action"],
                            command, False, "CONTROL_DENIED")
            else:
                self._audit(store, principal, command["review"].get("request_id"), command["action"],
                            command, True, "CONTROL_RECORDED")
                return result
        raise error

    def _authorize_locked(self, store, principal, command) -> bool:
        require(type(command) is dict and command.get("action") in ACTIONS, "INVALID_AUTH_ACTION")
        action = command["action"]
        review = command["review"]
        request_id = command.get("request_id", review.get("request_id"))
        preview_sha = command.get("preview_sha256", review.get("preview_sha256"))
        revision = review.get("reviewed_revision", review.get("approved_revision"))
        scope = review["approval_scope"]
        m = command["manifest"]
        require(m["request_id"] == request_id and m["reviewed_revision"] == revision, "COMMAND_BINDING")
        snapshot = store.get_preview(request_id, preview_sha)
        require(snapshot is not None, "COMMAND_BINDING")
        original = snapshot["manifest"]
        from scripts.ironman_jobs.ironman_operation_contracts import require_target_binding
        require_target_binding(m, command.get("requested_targets", review.get("requested_targets")))
        require(m["approval_scope"] == (scope if action in {"execute_change", "recover_worker"}
                                        else original["approval_scope"]), "COMMAND_SCOPE_BINDING")
        # Only the independently reviewed approval scope may differ from preview.
        require(digest({**m, "approval_scope": original["approval_scope"]}) == digest(original), "COMMAND_BINDING")
        if command.get("item") is not None:
            require(command["item"] in m["changes"], "COMMAND_ITEM_BINDING")
        if action in {"execute_change", "recover_worker"}:
            # Verify the exact existing reservation on the SAME connection as
            # current grants, revocations and audit. Never create a binding as
            # a side effect of an execution/recovery permission check.
            bound = store.inspect_execution_binding(
                request_id, preview_sha, command["approval_sha256"],
                approved_revision=revision, approval_scope=scope,
                requested_targets=command.get("requested_targets", review.get("requested_targets")),
                allow_revoked=action == "recover_worker")
            require(bound["manifest_sha256"] == digest(m), "COMMAND_BINDING")
        if (self._revoked(store, "token", canonical([principal.issuer, principal.token_id])) or
                self._revoked(store, "principal", canonical([principal.issuer, principal.subject]))):
            return False
        values = (principal.issuer, principal.subject, request_id, preview_sha, revision, scope, digest(original))
        for grant_id, raw in store.db.execute(
                "SELECT grant_id,payload FROM authority_grants WHERE binding_sha=?", (digest(values),)):
            grant = _json(raw.encode())
            require(digest(grant) == grant_id, "GRANT_RECORD_CORRUPT")
            if (self._revoked(store, "grant", grant_id) or
                    grant["granted_by"] not in self.verifier.administrators or
                    self._revoked(store, "principal", canonical([principal.issuer, grant["granted_by"]]))):
                continue
            if tuple(grant[k] for k in BINDING_FIELDS) == values:
                if self.clock() < min(grant["expires_at"], principal.expires_at) and action in grant["actions"]:
                    return True
        return False


def authority_from_host() -> HostReviewAuthority:
    """Configuration and assertion paths are supplied only by the existing host."""
    config_path = os.environ.get("IRONMAN_REVIEW_TRUST_CONFIG")
    assertion_path = os.environ.get("IRONMAN_REVIEW_ASSERTION_FILE")
    store_path = os.environ.get("IRONMAN_OPERATION_DRAFT_STORE")
    require(bool(config_path and assertion_path and store_path), "REVIEW_AUTHORITY_NOT_CONFIGURED")
    try:
        verifier = SignedIdentityVerifier(_json(read_host_file(Path(config_path), 65536)))
        return HostReviewAuthority(Path(store_path), verifier,
                                   lambda: read_host_file(Path(assertion_path), 32768).decode("ascii").strip())
    except (OSError, ValueError, TypeError) as exc:
        raise PermissionError("REVIEW_AUTHORITY_CONFIGURATION_INVALID") from exc
