"""MCP stdio process -> real Prefect API/process worker -> separate flow process.

One isolated pool/deployment uses the existing universal entrypoint. No six
previous in-process scenarios are replayed. All signing/provider state is lab-only.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import DeploymentUpdate, WorkPoolCreate
from prefect.settings import PREFECT_API_URL
from test_ironman_authorization import signed
from test_ironman_prefect_runtime import prefect_runtime
from test_ironman_unified_plan_workout_adapter import workout

from scripts.ironman_jobs.ironman_unified_changeset_engine import digest
from scripts.ironman_jobs.ironman_unified_prefect_flow import unified_changeset_flow


def test_worker_domain_envelope_preserves_preview_without_privileged_parameters():
    import pytest

    from scripts.ironman_jobs.ironman_worker_runtime import validate_worker_command
    command = {"mode": "preview", "manifest": {}, "requested_targets": []}
    validate_worker_command(command)
    for injection in ({"ledger_path": "/tmp/elsewhere"}, {"principal": "admin"},
                      {"writers": {}}, {"mode": "publish"}):
        with pytest.raises(PermissionError, match="WORKER_COMMAND_SHAPE"):
            validate_worker_command({**command, **injection})


async def start_process_lab(tmp_path):
    repo = Path(__file__).parents[1]
    home = tmp_path / "lab"
    home.mkdir(mode=0o700)
    (home / "assertions").mkdir(mode=0o700)
    key = ed25519.Ed25519PrivateKey.generate()
    config = {"issuer": "https://synthetic-worker.invalid", "audience": "worker-lab",
        "required_scope": "ironman:operator", "administrators": ["test-admin"],
        "keys": {"test-key": {"algorithm": "EdDSA", "public_key_pem": key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()}}}
    def private(name, data):
        path = home / name
        path.write_text(data)
        path.chmod(0o600)
        return path
    private("trust.json", json.dumps(config))
    private("issuer.pem", key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()).decode())
    private("control.json", "{}")
    with sqlite3.connect(home / "provider.sqlite3") as db:
        db.executescript("CREATE TABLE object(payload TEXT); CREATE TABLE writes(pid INTEGER);")
        db.execute("INSERT INTO object VALUES (?)", (json.dumps(workout(101)),))
    pool = "ironman-prefect-staging-process"
    async with get_client() as api:
        await api.create_work_pool(WorkPoolCreate(name=pool, type="process"))
    deployment = await unified_changeset_flow.to_deployment(name="scoped-plan-preview-once", work_pool_name=pool)
    deployment_id = await deployment.apply()
    async with get_client() as api:
        await api.update_deployment(deployment_id, DeploymentUpdate(pull_steps=[
            {"prefect.deployments.steps.set_working_directory": {"directory": str(repo)}}]))
    private("deployment.id", str(deployment_id))
    worker_config = {"deployment_id": str(deployment_id), "flow_sha256": hashlib.sha256(
        (repo / "scripts/ironman_jobs/ironman_unified_prefect_flow.py").read_bytes()).hexdigest(),
        "draft_store": str(home / "drafts.sqlite3"), "ledger_path": str(home / "execution.sqlite3"),
        "trust_config": str(home / "trust.json"), "assertion_directory": str(home / "assertions"),
        "read_transport": "local", "revocation_max_age_seconds": 300,
        "enabled_write_kinds": ["plan.workout.patch"]}
    private("worker.json", json.dumps(worker_config))
    env = dict(os.environ, PREFECT_API_URL=str(PREFECT_API_URL.value()), IRONMAN_LAB_HOME=str(home),
               PREFECT_WORKER_QUERY_SECONDS="1", PREFECT_WORKER_PREFETCH_SECONDS="1",
               TP_MCP_SKIP_STARTUP_VALIDATION="1")
    env.pop("PREFECT_API_KEY", None)
    env.pop("IRONMAN_OPERATOR_WORKER_CONFIG", None)
    for variable, name in {"IRONMAN_OPERATION_DRAFT_STORE": "drafts.sqlite3",
        "IRONMAN_OPERATION_EXECUTION_LEDGER": "execution.sqlite3", "IRONMAN_REVIEW_TRUST_CONFIG": "trust.json",
        "IRONMAN_REVIEW_ASSERTION_DIRECTORY": "assertions"}.items():
        env[variable] = str(home / name)
    env.pop("IRONMAN_REVIEW_ASSERTION_FILE", None)
    bootstrap = home / "bootstrap"
    bootstrap.mkdir(mode=0o700)
    (bootstrap / "sitecustomize.py").write_text("from worker_process_fixture import install_worker; install_worker()\n")
    basepath = os.pathsep.join([str(repo / "tests"), str(repo / "src"), str(repo), env.get("PYTHONPATH", "")])
    env["PYTHONPATH"] = basepath
    worker_env = dict(env, PYTHONPATH=str(bootstrap) + os.pathsep + basepath,
                      IRONMAN_OPERATOR_WORKER_CONFIG=str(home / "worker.json"))
    log = (home / "worker.log").open("w")
    process = subprocess.Popen([sys.executable, "-c",
        "import asyncio; from prefect.workers.process import ProcessWorker; "
        "asyncio.run(ProcessWorker(work_pool_name='ironman-prefect-staging-process').start())"],
        cwd=repo, env=worker_env, stdout=log, stderr=subprocess.STDOUT)
    from types import SimpleNamespace
    return SimpleNamespace(repo=repo, home=home, key=key, config=config, private=private,
                           deployment_id=deployment_id, env=env, process=process, log=log)


def stop_process_lab(lab):
    lab.process.terminate()
    try:
        lab.process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        lab.process.kill()
        lab.process.wait(timeout=5)
    lab.log.close()


async def test_separate_mcp_and_prefect_worker_restore_trusted_context(prefect_runtime, tmp_path):
    lab = await start_process_lab(tmp_path)
    repo, home, config, key, private = lab.repo, lab.home, lab.config, lab.key, lab.private
    env, deployment_id, process = lab.env, lab.deployment_id, lab.process
    seen = []
    async def call(client, mode, payload):
        command = {"mode": mode, "manifest": payload, "requested_targets": [{"kind": "plan.workout.patch",
            "target": {"provider": "trainingpeaks", "owner_id": 2116886, "container_kind": "training_plan",
                       "container_id": 501, "resource_id": 101}}]}
        now = int(time.time())
        proof = {"iss": config["issuer"], "aud": config["audience"], "scope": config["required_scope"],
            # Each call here is a separately admitted operation. The transport
            # retransmission case holds intent stable in its dedicated test.
            "sub": "test-user", "jti": "ingress", "run_id": str(uuid4()), "iat": now - 1,
            "nbf": now - 1, "exp": now + 600, "command_sha256": digest(command)}
        private("ingress.jwt", signed(key, proof))
        result = await client.call_tool("tp_ironman_request", command)
        decoded = json.loads(result.content[0].text)
        seen.append(decoded)
        return decoded
    try:
        transport = stdio_client(StdioServerParameters(command=sys.executable,
            args=["-c", "from worker_process_fixture import run_mcp; run_mcp()"], env=env, cwd=repo))
        async with Client(transport, read_timeout_seconds=120) as client:
            before, after = workout(101), {**workout(101), "title": "Multiprocess reviewed"}
            draft = {"schema": "IRONMAN_OPERATION_INPUT_V1", "request_key": "separate-process-request",
                "items": [{"id": "patch01", "kind": "plan.workout.patch",
                    "target": {"provider": "trainingpeaks", "owner_id": 2116886, "container_kind": "training_plan",
                               "container_id": 501, "resource_id": 101}, "depends_on": [],
                    "before_sha256": digest(before), "payload": {"desired": after, "fields": ["title"]}}]}
            prepared = await call(client, "prepare", draft)
            assert not prepared.get("isError"), (prepared, (home / "worker.log").read_text()[-4000:])
            preview = await call(client, "preview_draft", {"schema": "IRONMAN_DRAFT_PREVIEW_INPUT_V1",
                "request_id": prepared["request_id"], "after_images": {"patch01": after}, "pinned_revision": "b" * 40})
            assert not preview.get("isError"), preview
            review = {"schema": "IRONMAN_REVIEW_INPUT_V1", "request_id": prepared["request_id"],
                "preview_sha256": preview["preview_sha256"], "reviewed_revision": "b" * 40,
                "approval_scope": "approved:worker-lab"}
            approved = await call(client, "approve_preview", review)
            review["approval_sha256"] = approved["approval_sha256"]
            assert (await call(client, "bind_execution", review))["state"] == "EXECUTION_BOUND"
            assert (await call(client, "execute_bound", review))["request_state"] == "WORK_COMPLETE"
            assert (await call(client, "execute_bound", review))["request_state"] == "WORK_COMPLETE"
            for flag in ("wrong_command", "wrong_origin", "omit_assertion", "stale_revocations"):
                private("control.json", json.dumps({flag: True}))
                if flag == "stale_revocations":
                    with sqlite3.connect(home / "drafts.sqlite3") as db:
                        db.execute("UPDATE authority_revocation_checkpoint SET observed_at=0")
                assert (await call(client, "prepare", draft))["isError"]
            private("control.json", "{}")
            (home / "worker.json").rename(home / "worker.off")
            assert (await call(client, "prepare", draft))["isError"]
        with sqlite3.connect(home / "provider.sqlite3") as db:
            pids = db.execute("SELECT pid FROM writes").fetchall()
            assert len(pids) == 1
            assert pids[0][0] not in {os.getpid(), process.pid, int((home / "mcp.pid").read_text())}
        async with get_client() as api:
            import asyncio

            from prefect.client.schemas.filters import FlowRunFilter, FlowRunFilterDeploymentId
            from prefect.client.schemas.sorting import FlowRunSort
            from prefect.states import Scheduled
            (home / "worker.off").rename(home / "worker.json")
            injected = await api.create_flow_run_from_deployment(deployment_id, parameters={
                "mode": "prepare", "manifest": draft, "requested_targets": [],
                "ledger_path": str(home / "forbidden.sqlite3")}, state=Scheduled())
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                injected = await api.read_flow_run(injected.id)
                if injected.state and injected.state.is_final():
                    break
                await asyncio.sleep(0.25)
            assert injected.state.is_failed()
            assert "WORKER_PRIVILEGED_PARAMETERS_FORBIDDEN" in injected.state.message
            assert not (home / "forbidden.sqlite3").exists()
            runs = await api.read_flow_runs(flow_run_filter=FlowRunFilter(
                deployment_id=FlowRunFilterDeploymentId(any_=[deployment_id])), limit=20, sort=FlowRunSort.ID_DESC)
            assert len(runs) == 12
            assert sum(run.state.is_completed() for run in runs) == 6
            assert sum(run.state.is_failed() for run in runs) == 6
            messages = "\n".join(run.state.message or "" for run in runs)
            for code in ("ASSERTION_COMMAND_MISMATCH", "ASSERTION_INVOCATION_MISMATCH",
                         "REVOCATIONS_MISSING_OR_STALE", "UNSAFE_AUTH_FILE"):
                assert code in messages
            for run in runs:
                if run.id == injected.id:
                    continue
                assert set(run.parameters) == {"mode", "manifest", "requested_targets"}
                assert "issuer.pem" not in json.dumps(run.parameters)
        print("MULTIPROCESS_PASS: distinct MCP/worker/flow PIDs; one synthetic PUT; six worker admission denials")
    finally:
        stop_process_lab(lab)
