"""Shared request selectors and the trusted review boundary; no provider I/O."""
from typing import Any, Protocol
import json


class TargetBindingError(ValueError):
    pass


def require_target_binding(manifest: dict[str, Any], requested: Any) -> None:
    """One selector per kind/resource, even for a chain editing it twice."""
    def check(ok, code):
        if not ok:
            raise TargetBindingError(code)

    check(type(requested) is list and bool(requested), "REQUEST_TARGET_BINDING_REQUIRED")
    check(len(requested) <= 1000, "REQUEST_TARGET_BINDING_LIMIT")
    keys = ("provider", "owner_id", "container_kind", "container_id", "resource_id")
    expected = set()
    for entry in requested:
        check(type(entry) is dict and set(entry) == {"kind", "target"},
              "REQUEST_TARGET_BINDING_SHAPE")
        target = entry["target"]
        check(type(entry["kind"]) is str and type(target) is dict and set(target) == set(keys),
              "REQUEST_TARGET_BINDING_SHAPE")
        check(target["provider"] == "trainingpeaks" and
              type(target["owner_id"]) is int and target["owner_id"] == manifest["owner_id"] and
              target["container_kind"] in ("training_plan", "workout_library") and
              all(type(target[k]) is int and target[k] > 0
                  for k in ("container_id", "resource_id")), "REQUEST_TARGET_BINDING_INVALID")
        identity = (entry["kind"], *(target[k] for k in keys))
        check(identity not in expected, "REQUEST_TARGET_BINDING_DUPLICATE")
        expected.add(identity)
    actual = {(item["kind"], *(item["target"][k] for k in keys))
              for item in manifest["changes"]}
    check(expected == actual, "STOP_TARGET_MISMATCH")


class ReviewAuthorizer(Protocol):
    """Trusted host verifies identity, current grants/revocation and this command.

    This dependency is installed in code on the existing runtime, never selected
    by a flow parameter, module path, request payload or stored approval SHA.
    """
    def authorize(self, command: dict[str, Any]) -> bool: ...
    def run_control(self, command: dict[str, Any], store) -> dict[str, Any]: ...


def get_review_authorizer() -> ReviewAuthorizer:
    """Resolve pinned host trust; missing/invalid configuration still denies."""
    from scripts.ironman_jobs.ironman_authorization import authority_from_host
    return authority_from_host()


def apply_review_control(store, command):
    """Common persistence dispatch; authority must hold its transaction first."""
    review, action = command["review"], command["action"]
    options = dict(approved_revision=review["reviewed_revision"], approval_scope=review["approval_scope"],
                   requested_targets=command["requested_targets"])
    if action == "approve_preview":
        return store.record_approval(review["request_id"], review["preview_sha256"], **options)
    if action == "bind_execution":
        return store.bind_execution(review["request_id"], review["preview_sha256"], review["approval_sha256"], **options)
    if action == "revoke_approval":
        return store.revoke_approval(review["request_id"], review["preview_sha256"], review["approval_sha256"], **options)
    raise PermissionError("UNSUPPORTED_REVIEW_CONTROL")


class BoundExecutionAuthorization:
    """Reusable guard for a future reviewed writer, not a publishing route.

    Re-open the shared store and consult the trusted authority on every check.
    A previously returned manifest or approval SHA never authorizes itself.
    """
    def __init__(self, store_path, request_id, preview_sha, approval_sha, *,
                 approved_revision, approval_scope, requested_targets):
        self.store_path = store_path
        self.request_id, self.preview_sha, self.approval_sha = request_id, preview_sha, approval_sha
        self.review = json.loads(json.dumps(dict(
            approved_revision=approved_revision, approval_scope=approval_scope,
            requested_targets=requested_targets)))

    action = "execute_change"

    def __call__(self, manifest: dict, item: dict | None) -> bool:
        from scripts.ironman_jobs.ironman_dynamic_request_store import DraftStore
        from scripts.ironman_jobs.ironman_unified_changeset_engine import digest
        command = json.loads(json.dumps({
            "action": self.action, "request_id": self.request_id,
            "preview_sha256": self.preview_sha, "approval_sha256": self.approval_sha,
            "review": self.review, "manifest": manifest, "item": item,
        }))
        store = DraftStore(self.store_path)
        try:
            snapshot = store.get_preview(self.request_id, self.preview_sha)
            if snapshot is None or digest({**snapshot["manifest"],
                                           "approval_scope": self.review["approval_scope"]}) != digest(manifest):
                raise PermissionError("EXECUTION_MANIFEST_BINDING_MISMATCH")
            if get_review_authorizer().authorize(command) is not True:
                raise PermissionError("EXECUTION_AUTHORIZATION_DENIED")
            operation = store.inspect_execution_binding if self.action == "recover_worker" else store.bind_execution
            bound = operation(self.request_id, self.preview_sha, self.approval_sha, **self.review)
            if bound["manifest_sha256"] != digest(manifest):
                raise PermissionError("EXECUTION_MANIFEST_BINDING_MISMATCH")
        finally:
            store.close()
        return True


class BoundRecoveryAuthorization(BoundExecutionAuthorization):
    """Recovery permission allows readback of a revoked binding, never execution."""
    action = "recover_worker"
