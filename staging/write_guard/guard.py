"""IRONMAN isolated write-gate POC, v0.2.

No provider credentials or network calls. Provider and authorizer are injected.
The ledger is durable for a SINGLE host sharing one local SQLite database.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Protocol

from routing import DOCS_CAPABILITIES, CapabilityRegistry, RouteDecision


class GuardError(Exception):
    pass


class ProviderError(GuardError):
    pass


class ReconciliationRequired(GuardError):
    """State may have changed; never blindly replay an uncertain write."""
    pass


class ExplicitSecurityDenial(ProviderError):
    """A confirmed authorization/security denial for this exact operation."""
    pass


@dataclass(frozen=True)
class Document:
    revision: str
    text: str


class DocsProvider(Protocol):
    def read(self, document_id: str) -> Document: ...
    def replace_once(self, document_id: str, required_revision: str, old: str, new: str) -> None: ...


@dataclass(frozen=True)
class Patch:
    operation_id: str
    document_id: str
    proven_path: str
    expected_revision: str
    old: str
    new: str
    checkpoint: str
    approval_ref: str

    def digest(self) -> str:
        canonical = json.dumps(self.__dict__, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


class Authorizer(Protocol):
    def permits(self, patch: Patch) -> bool:
        """Independently validate actor, target AND entire intended modification."""
        ...


class DocsWriteGuard:
    """Gate for one document mutation class, using an isolated durable ledger.

    The provider-side required_revision must also be enforced. Distinct operations
    on the same doc are serialized by the provider's revision precondition, not
    by this SQLite DB. Multi-host use requires a distributed coordination layer.
    """

    def __init__(self, provider: DocsProvider, authorizer: Authorizer,
                 ledger_path: str, allowed_documents: set[str],
                 routing: CapabilityRegistry = DOCS_CAPABILITIES):
        self.provider = provider
        self.authorizer = authorizer
        self.ledger_path = ledger_path
        self.allowed_documents = set(allowed_documents)
        self.routing = routing
        with self._conn() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
                document_id TEXT NOT NULL, state TEXT NOT NULL, result TEXT)''')

    def _conn(self):
        return sqlite3.connect(self.ledger_path, timeout=20)

    @staticmethod
    def _validate(p: Patch) -> None:
        required = (p.operation_id, p.document_id, p.proven_path,
                    p.expected_revision, p.old, p.new, p.checkpoint,
                    p.approval_ref)
        if any(not isinstance(x, str) or not x.strip() for x in required):
            raise GuardError('Missing required operation scope, approval or evidence')
        if p.old == p.new:
            raise GuardError('No-op patch')
        if p.checkpoint not in p.new or p.checkpoint in p.old:
            raise GuardError('Missing unique new checkpoint marker')

    def plan(self) -> RouteDecision:
        """A capability label is never self-authorization."""
        return self.routing.resolve('google_docs', 'replace_text_once')

    def _authorize(self, p: Patch) -> None:
        selection = self.plan()
        if selection.state != 'READY':
            raise GuardError('Docs capability not verified: ' + selection.action)
        if p.proven_path != 'AUTO':
            good = any(c.path_id == p.proven_path and c.state == 'VERIFIED'
                       and c.evidence and c.resource == 'google_docs'
                       and c.operation == 'replace_text_once'
                       for c in self.routing.capabilities)
            if not good:
                raise GuardError('Requested path lacks verified evidence for Docs text writes')
        if p.document_id not in self.allowed_documents:
            raise GuardError('Document outside explicit allowlist')
        if not self.authorizer.permits(p):
            raise GuardError('Authorization not verified for this exact modification')

    @staticmethod
    def _matches(p: Patch, d: Document) -> bool:
        return d.text.count(p.checkpoint) == 1 and p.new in d.text

    def _set_state(self, p: Patch, state: str, detail: str | None = None) -> None:
        with self._conn() as db:
            db.execute('UPDATE operations SET state=?, result=? WHERE operation_id=?',
                       (state, detail, p.operation_id))

    def execute(self, p: Patch) -> str:
        self._validate(p)
        self._authorize(p)
        digest = p.digest()
        # Read before acquiring the journal transaction to avoid network I/O
        # while holding an exclusive SQLite lock.
        before = self.provider.read(p.document_id)
        with self._conn() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT digest, state FROM operations WHERE operation_id=?',
                             (p.operation_id,)).fetchone()
            if row is not None and row[0] != digest:
                raise GuardError('Idempotency-key collision: payload changed')
            if row is not None and row[1] in ('SECURITY_DENIED', 'UNCERTAIN_SECURITY_DENIAL'):
                raise GuardError('Prior explicit security denial: no retry')
            if p.checkpoint in before.text:
                if not self._matches(p, before):
                    raise GuardError('Checkpoint present but content does not match')
                db.execute('INSERT OR REPLACE INTO operations VALUES (?,?,?,?,?)',
                           (p.operation_id, digest, p.document_id, 'VERIFIED', before.revision))
                return 'ALREADY_VERIFIED'
            if row is not None and row[1] == 'VERIFIED':
                # Preflight read may have raced with the first execution.
                # Recheck once instead of misclassifying a legitimate replay.
                latest = self.provider.read(p.document_id)
                if self._matches(p, latest):
                    return 'ALREADY_VERIFIED'
                raise GuardError('Verified checkpoint unexpectedly disappeared')
            if row is not None and row[1] in ('IN_FLIGHT', 'UNCERTAIN'):
                raise ReconciliationRequired('Earlier write may be in flight; inspect provider, no blind retry')
            if before.revision != p.expected_revision:
                raise GuardError('Stale revision: re-evaluate original delta')
            if before.text.count(p.old) != 1:
                raise GuardError('Ambiguous or missing insertion point')
            # Commit the attempt BEFORE the external side effect. If the process
            # crashes, IN_FLIGHT survives and a rerun must reconcile by readback.
            db.execute('INSERT OR REPLACE INTO operations VALUES (?,?,?,?,?)',
                       (p.operation_id, digest, p.document_id, 'IN_FLIGHT', before.revision))
        provider_error = None
        try:
            self.provider.replace_once(p.document_id, p.expected_revision, p.old, p.new)
        except Exception as exc:
            provider_error = exc
        try:
            after = self.provider.read(p.document_id)
        except Exception as exc:
            state = ('UNCERTAIN_SECURITY_DENIAL' if isinstance(provider_error, ExplicitSecurityDenial)
                     else 'UNCERTAIN')
            self._set_state(p, state, 'ReadbackUnavailable:' + type(exc).__name__)
            raise ReconciliationRequired('Provider readback unavailable; do not replay') from exc
        if self._matches(p, after):
            self._set_state(p, 'VERIFIED', after.revision)
            return 'VERIFIED'
        if p.checkpoint in after.text:
            self._set_state(p, 'UNCERTAIN', 'MarkerMismatch')
            raise ReconciliationRequired('Checkpoint exists but expected content differs')
        if isinstance(provider_error, ExplicitSecurityDenial):
            self._set_state(p, 'SECURITY_DENIED', 'ExplicitSecurityDenial')
            raise ExplicitSecurityDenial('Provider explicitly denied this operation; retry forbidden') from provider_error
        if provider_error is not None:
            self._set_state(p, 'FAILED_NO_CHANGE', type(provider_error).__name__)
            raise ProviderError('Provider write did not verify; state checked') from provider_error
        self._set_state(p, 'UNCERTAIN', 'NoPostwriteMatch')
        raise ReconciliationRequired('Provider response did not match readback; inspect before retry')
