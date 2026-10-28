"""Synthetic issuer/provider bootstrap, imported ONLY by isolated test processes."""
import json
import os
import sqlite3
import time
from contextvars import ContextVar
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from test_ironman_authorization import signed

from scripts.ironman_jobs.ironman_authorization import (
    ACTIONS,
    HostReviewAuthority,
    SignedIdentityVerifier,
    assertion_path_for_invocation,
    read_host_file,
)
from scripts.ironman_jobs.ironman_unified_changeset_engine import digest


def root():
    return Path(os.environ["IRONMAN_LAB_HOME"])


class Response:
    is_error = False
    def __init__(self, data):
        self.data = data


class SyntheticHTTP:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        return False
    async def _get_user_data(self):
        return {"personId": 2116886}
    async def get(self, route):
        if route == "/plans/v1/plans/501":
            return Response({"planId": 501, "ownerPersonId": 2116886, "planPersonId": 600,
                             "startDate": "2027-03-29", "weekCount": 1})
        if route.startswith("/plans/v1/plans/501/workouts/"):
            with sqlite3.connect(root() / "provider.sqlite3") as db:
                return Response([json.loads(db.execute("SELECT payload FROM object").fetchone()[0])])
        raise AssertionError("UNEXPECTED_SYNTHETIC_ROUTE")


def put_one(plan_id, workout_id, desired):
    assert (plan_id, workout_id) == (501, 101)
    with sqlite3.connect(root() / "provider.sqlite3") as db:
        db.execute("UPDATE object SET payload=?", (json.dumps(desired),))
        db.execute("INSERT INTO writes VALUES (?)", (os.getpid(),))
    delay = json.loads((root() / "control.json").read_text()).get("post_write_delay_seconds", 0)
    if delay:
        (root() / "provider-committed").write_text(str(time.time()))
        time.sleep(delay)


def install_worker():
    import tp_mcp.client
    from scripts.ironman_jobs.ironman_unified_plan_workout_adapter import ReviewedClassicPlanPatchAdapter
    from scripts.ironman_jobs.ironman_worker_runtime import install_worker_adapters
    tp_mcp.client.TPClient = SyntheticHTTP
    install_worker_adapters(lambda: {"plan.workout.patch": ReviewedClassicPlanPatchAdapter(put_one=put_one)})


def make_invocation_issuer(config, key):
    home = root()
    verifier = SignedIdentityVerifier(config)
    grants = set()
    def claims(origin, subject="test-user", **extra):
        now = int(time.time())
        return {"iss": config["issuer"], "aud": config["audience"], "scope": config["required_scope"],
                "sub": subject, "jti": subject + ":" + origin, "run_id": origin,
                "iat": now - 1, "nbf": now - 1, "exp": now + 600, **extra}

    def provision(origin, command):
        control = json.loads((home / "control.json").read_text())
        admin_token = signed(key, claims(origin, "test-admin"))
        admin = HostReviewAuthority(home / "drafts.sqlite3", verifier, lambda: admin_token,
                                    invocation_id_provider=lambda: origin)
        if not control.get("stale_revocations"):
            admin.refresh_revocations(1)
        if command["mode"] in {"approve_preview", "bind_execution", "execute_bound", "revoke_approval"}:
            payload = command["manifest"]
            selector = (payload["request_id"], payload["preview_sha256"])
            if selector not in grants:
                user = verifier.verify(signed(key, claims(origin)))
                admin.grant(user, *selector, approval_scope=payload["approval_scope"],
                            actions=sorted(ACTIONS), expires_at=int(time.time()) + 500)
                grants.add(selector)
        if control.get("omit_assertion"):
            return
        target = assertion_path_for_invocation(home / "assertions", origin)
        token = signed(key, claims("wrong-flow" if control.get("wrong_origin") else origin,
                                  command_sha256="0" * 64 if control.get("wrong_command") else digest(command)))
        pending = target.with_suffix(".pending")
        pending.write_text(token)
        pending.chmod(0o600)
        pending.replace(target)

    return provision


def run_mcp():
    from scripts.ironman_jobs.ironman_prefect_dispatch import DispatchIdentity, PrefectProcessLauncher
    from tp_mcp.operator_runtime import OperatorBindings, bind_operator_runtime
    from tp_mcp.server import run_server
    home = root()
    config = json.loads(read_host_file(home / "trust.json", 65536))
    key = serialization.load_pem_private_key(read_host_file(home / "issuer.pem", 65536), password=None)
    verifier = SignedIdentityVerifier(config)
    admitted_identity = ContextVar("synthetic_ingress_identity", default=None)
    (home / "mcp.pid").write_text(str(os.getpid()))
    def admit(command):
        principal = verifier.verify(read_host_file(home / "ingress.jwt", 32768).decode())
        allowed = principal.subject == "test-user" and principal.command_sha256 == digest(command)
        if allowed:
            admitted_identity.set(principal)
        return allowed

    def resolve_identity(command):
        principal = admitted_identity.get()
        if (principal is None or principal.expires_at <= time.time() or
                principal.command_sha256 != digest(command)):
            raise PermissionError("SYNTHETIC_ADMISSION_REQUIRED")
        return DispatchIdentity(principal.issuer, principal.subject, principal.invocation_id)

    provision = make_invocation_issuer(config, key)

    deployment = (home / "deployment.id").read_text().strip()
    launcher = PrefectProcessLauncher(deployment, provision, resolve_identity=resolve_identity, timeout=90)
    bindings = OperatorBindings(str(home / "execution.sqlite3"), admit, launcher)
    with bind_operator_runtime(bindings):
        run_server()


def run_http_mcp():
    """One ephemeral TLS lab process; never imported by production startup."""
    import uvicorn

    from scripts.ironman_jobs.ironman_authorization import OAuthHumanIdentityVerifier, OAuthMCPTokenVerifier
    from scripts.ironman_jobs.ironman_prefect_dispatch import DispatchIdentity, PrefectProcessLauncher
    from tp_mcp.operator_http import OperatorHTTPConfig, current_http_access_token
    from tp_mcp.operator_runtime import OperatorBindings
    from tp_mcp.server import create_operator_http_app

    home = root()
    worker_trust = json.loads(read_host_file(home / "trust.json", 65536))
    key = serialization.load_pem_private_key(read_host_file(home / "issuer.pem", 65536), password=None)
    port = int((home / "http-port").read_text())
    resource = f"https://127.0.0.1:{port}/mcp"
    trust = {k: worker_trust[k] for k in ("issuer", "required_scope", "keys")}
    identities = OAuthHumanIdentityVerifier({**trust, "audience": resource,
        "human_subjects": ["test-user"], "client_ids": ["synthetic-http-client"]})

    async def current(_):
        return not json.loads((home / "control.json").read_text()).get("ingress_revoked", False)

    # This synthetic IdP attests a stable operation intent and command. It is
    # a test-only host contract, not a claim about a real provider's capabilities.
    def verified_intent(command):
        claims = identities.verifier._verified_claims(current_http_access_token().token, access_token=True)
        if claims.get("command_sha256") != digest(command) or not claims.get("intent_id"):
            raise PermissionError("SYNTHETIC_COMMAND_INTENT_REQUIRED")
        return DispatchIdentity(claims["iss"], claims["sub"], claims["intent_id"])

    base_issuer = make_invocation_issuer(worker_trust, key)

    def provision(origin, command):
        base_issuer(origin, command)
        with (home / "issued.jsonl").open("a") as log:
            log.write(json.dumps({"flow_id": origin, "pid": os.getpid(), "command_sha256": digest(command)}) + "\n")
        (home / "issued.jsonl").chmod(0o600)

    launcher = PrefectProcessLauncher((home / "deployment.id").read_text().strip(), provision,
                                     resolve_identity=verified_intent)  # Native 90s budget, unchanged.

    def bindings_for(access):
        def admit(command):
            identity = verified_intent(command)
            return identity.subject == access.subject
        return OperatorBindings(str(home / "execution.sqlite3"), admit, launcher)

    app = create_operator_http_app(config=OperatorHTTPConfig(resource, worker_trust["issuer"],
        worker_trust["required_scope"], "127.0.0.1", port),
        token_verifier=OAuthMCPTokenVerifier(identities, revocations_current=current), bindings_for=bindings_for)
    (home / "http-mcp.pid").write_text(str(os.getpid()))
    uvicorn.run(app, host="127.0.0.1", port=port, proxy_headers=False, access_log=False,
                ssl_keyfile=str(home / "tls-key.pem"), ssl_certfile=str(home / "tls-cert.pem"), log_level="warning")
