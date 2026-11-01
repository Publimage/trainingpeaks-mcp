"""Capability-first Proven Path routing for the isolated IRONMAN write guard.

An operation selects a verified *capability class*, not a path label that the
assistant is required to remember. New capabilities can be validated offline,
but their first provider write requires separate authorization and canary.
This is not a provider service or a security bypass.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Capability:
    resource: str
    operation: str
    path_id: str
    evidence: str
    state: str = "VERIFIED"
    priority: int = 0


@dataclass(frozen=True)
class RouteDecision:
    state: str  # READY, CANARY_REQUIRED, VALIDATION_REQUIRED
    resource: str
    operation: str
    path_id: str | None
    evidence: str | None
    action: str


class CapabilityRegistry:
    """Inject trusted registry data; do not accept user/LLM self-certification."""

    def __init__(self, capabilities: tuple[Capability, ...]):
        self.capabilities = tuple(capabilities)

    def resolve(self, resource: str, operation: str) -> RouteDecision:
        matches = [c for c in self.capabilities
                   if c.resource == resource and c.operation == operation]
        proven = sorted((c for c in matches if c.state == "VERIFIED" and c.evidence),
                        key=lambda x: x.priority, reverse=True)
        if proven:
            c = proven[0]
            return RouteDecision("READY", resource, operation, c.path_id,
                                 c.evidence, "Reuse verified resource-class writer")
        candidates = [c for c in matches if c.state in ("CANDIDATE", "OFFLINE_TESTED")]
        if candidates:
            c = candidates[0]
            return RouteDecision("CANARY_REQUIRED", resource, operation, c.path_id,
                                 c.evidence or None,
                                 "Prepare scoped provider canary and approval; no unverified live write")
        return RouteDecision("VALIDATION_REQUIRED", resource, operation, None,
                             None, "Discover existing capability or validate candidate without modifying production")

    def evaluate_candidate_offline(
        self, resource: str, operation: str, probe: Callable[[], bool]
    ) -> RouteDecision:
        """A read-only / simulated probe never promotes a path to VERIFIED."""
        current = self.resolve(resource, operation)
        if current.state == "READY":
            return current
        if not probe():
            return RouteDecision("VALIDATION_REQUIRED", resource, operation,
                                 current.path_id, current.evidence,
                                 "Offline probe failed; diagnose without real provider write")
        return RouteDecision("CANARY_REQUIRED", resource, operation,
                             current.path_id, current.evidence,
                             "Offline probe passed; provider canary and authorization still required")


DOCS_CAPABILITIES = CapabilityRegistry((
    Capability(
        resource="google_docs", operation="replace_text_once",
        path_id="DRIVE-DOC-004",
        evidence="V1 00C: verified targeted update with revision and readback",
        priority=100,
    ),
    Capability(
        resource="google_docs", operation="replace_text_once",
        path_id="KB-DOCS-RELIABLE-WRITE-033",
        evidence="V1 00C: verified Docs write reliability procedure",
        priority=80,
    ),
))
