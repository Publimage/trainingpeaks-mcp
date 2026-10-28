"""ONE release proof: real TLS HTTP/MCP, real Prefect worker, disposable provider.

No hosted Tunnel, production IdP or TrainingPeaks request. A real 125s provider
completion delay crosses the documented 120s hosted deadline without scaling it.
"""

import asyncio
import datetime
import ipaddress
import json
import os
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
from uuid import UUID

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from prefect.client.orchestration import get_client
from prefect.client.schemas.filters import FlowRunFilter, FlowRunFilterDeploymentId
from prefect.client.schemas.sorting import FlowRunSort
from test_ironman_authorization import signed
from test_ironman_prefect_runtime import prefect_runtime  # noqa: F401 — shared isolated API fixture
from test_ironman_unified_plan_workout_adapter import workout
from test_ironman_worker_process import start_process_lab, stop_process_lab

from scripts.ironman_jobs.ironman_unified_changeset_engine import Ledger, digest


def tls_for_lab(lab):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IRONMAN disposable local lab")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    lab.private(
        "tls-key.pem",
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode(),
    )
    lab.private("tls-cert.pem", cert.public_bytes(serialization.Encoding.PEM).decode())
    return ssl.create_default_context(cafile=str(lab.home / "tls-cert.pem"))


def start_http(lab):
    log = (lab.home / "http.log").open("a")
    process = subprocess.Popen(
        [sys.executable, "-c", "from worker_process_fixture import run_http_mcp; run_http_mcp()"],
        cwd=lab.repo,
        env=lab.env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    log.close()
    return process


def stop_http(process):
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


async def ready(api, process, lab):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        assert process.poll() is None, (lab.home / "http.log").read_text()[-3000:]
        try:
            response = await api.get("/.well-known/oauth-protected-resource/mcp")
            if response.status_code == 200:
                return
        except httpx.TransportError:
            pass
        await asyncio.sleep(0.2)
    raise AssertionError("LOCAL_HTTP_LAB_NOT_READY")


@pytest.mark.usefixtures("prefect_runtime")
async def test_one_http_oauth_worker_release_with_long_run_and_producer_restart(tmp_path):
    lab = await start_process_lab(tmp_path)
    tls = tls_for_lab(lab)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    lab.private("http-port", str(port))
    resource = f"https://127.0.0.1:{port}/mcp"
    process = start_http(lab)
    first_mcp_pid = process.pid
    before, after = workout(101), {**workout(101), "title": "Integrated HTTP release lab"}
    target = {
        "kind": "plan.workout.patch",
        "target": {
            "provider": "trainingpeaks",
            "owner_id": 2116886,
            "container_kind": "training_plan",
            "container_id": 501,
            "resource_id": 101,
        },
    }

    async def call(api, mode, payload, *, renewed=False):
        command = {"mode": mode, "manifest": payload, "requested_targets": [target]}
        now = int(time.time())
        token = signed(
            lab.key,
            {
                "iss": lab.config["issuer"],
                "aud": resource,
                "sub": "test-user",
                "client_id": "synthetic-http-client",
                "scope": "ironman:operator",
                "iat": now - 1,
                "exp": now + 600,
                "jti": "renewed-token" if renewed else "initial-token",
                "intent_id": "release-http:" + mode,
                "command_sha256": digest(command),
            },
            {"kid": "test-key", "alg": "EdDSA", "typ": "at+jwt"},
        )
        response = await api.post(
            "/mcp",
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            json={
                "jsonrpc": "2.0",
                "id": mode,
                "method": "tools/call",
                "params": {"name": "tp_ironman_request", "arguments": command},
            },
        )
        assert response.status_code == 200, response.text
        reply = response.json()
        assert "result" in reply, reply
        decoded = json.loads(reply["result"]["content"][0]["text"])
        assert not decoded.get("isError"), (decoded, (lab.home / "worker.log").read_text()[-3000:])
        return decoded, command

    try:
        async with httpx.AsyncClient(base_url=resource.removesuffix("/mcp"), verify=tls, timeout=115) as api:
            await ready(api, process, lab)
            draft = {
                "schema": "IRONMAN_OPERATION_INPUT_V1",
                "request_key": "one-http-worker-release",
                "items": [
                    {
                        "id": "patch01",
                        **target,
                        "depends_on": [],
                        "before_sha256": digest(before),
                        "payload": {"desired": after, "fields": ["title"]},
                    }
                ],
            }
            prepared, _ = await call(api, "prepare", draft)
            print("HTTP_WORKER_RELEASE: prepare complete", flush=True)
            preview, _ = await call(
                api,
                "preview_draft",
                {
                    "schema": "IRONMAN_DRAFT_PREVIEW_INPUT_V1",
                    "request_id": prepared["request_id"],
                    "after_images": {"patch01": after},
                    "pinned_revision": "b" * 40,
                },
            )
            review = {
                "schema": "IRONMAN_REVIEW_INPUT_V1",
                "request_id": prepared["request_id"],
                "preview_sha256": preview["preview_sha256"],
                "reviewed_revision": "b" * 40,
                "approval_scope": "approved:worker-lab",
            }
            approved, _ = await call(api, "approve_preview", review)
            review["approval_sha256"] = approved["approval_sha256"]
            bound, _ = await call(api, "bind_execution", review)
            assert bound["state"] == "EXECUTION_BOUND"
            print("HTTP_WORKER_RELEASE: preview/approval/binding complete; starting >120s execution", flush=True)
            lab.private("control.json", json.dumps({"post_write_delay_seconds": 125}))
            started = time.monotonic()
            pending, command = await call(api, "execute_bound", review)
            response_seconds = time.monotonic() - started
            assert pending["request_state"] == "DISPATCH_UNCERTAIN", pending
            assert pending["provider_retry_allowed"] is False and response_seconds < 120
            flow_id = UUID(pending["flow_run_id"])
            assert (lab.home / "provider-committed").exists()
            with sqlite3.connect(lab.home / "provider.sqlite3") as db:
                assert db.execute("SELECT count(*) FROM writes").fetchone() == (1,)
            print(
                f"HTTP_WORKER_RELEASE: response in {response_seconds:.2f}s, same flow retained, one committed PUT",
                flush=True,
            )
        stop_http(process)
        process = start_http(lab)
        async with httpx.AsyncClient(base_url=resource.removesuffix("/mcp"), verify=tls, timeout=115) as api:
            await ready(api, process, lab)
            # Automatic caller reconciliation with the same admitted intent,
            # after a new producer process, new HTTP client and renewed bearer.
            recovered, _ = await call(api, "execute_bound", review, renewed=True)
            elapsed = time.monotonic() - started
            assert recovered["request_state"] == "DISPATCH_RESULT_REUSED", recovered
            assert recovered["flow_run_id"] == str(flow_id)
            assert recovered["historical_result"]["request_state"] == "WORK_COMPLETE"
            assert recovered["new_execution"] is False and recovered["provider_retry_allowed"] is False
            assert elapsed > 120, elapsed
        with sqlite3.connect(lab.home / "provider.sqlite3") as db:
            writes = db.execute("SELECT pid FROM writes").fetchall()
            assert len(writes) == 1 and json.loads(db.execute("SELECT payload FROM object").fetchone()[0]) == after
        ledger = Ledger(lab.home / "execution.sqlite3")
        try:
            assert ledger.status(prepared["request_id"], "patch01") == "DONE_VERIFIED"
        finally:
            ledger.close()
        async with get_client() as api:
            runs = await api.read_flow_runs(
                flow_run_filter=FlowRunFilter(deployment_id=FlowRunFilterDeploymentId(any_=[lab.deployment_id])),
                limit=20,
                sort=FlowRunSort.ID_DESC,
            )
            assert len(runs) == 5 and all(r.state.is_completed() for r in runs)
            receipt_response = await api.request(
                "POST",
                "/artifacts/filter",
                json={
                    "artifacts": {
                        "flow_run_id": {"any_": [str(flow_id)]},
                        "key": {"any_": ["ironman-request-" + str(flow_id)]},
                    },
                    "limit": 2,
                    "offset": 0,
                    "sort": "CREATED_DESC",
                },
            )
            receipts = receipt_response.json()
            assert len(receipts) == 1
            receipt = receipts[0]["data"]
            assert receipt["flow_run_id"] == str(flow_id) and receipt["command_sha256"] == digest(command)
            assert receipt["result"]["request_state"] == "WORK_COMPLETE"
            for run in runs:
                assert set(run.parameters) == {"mode", "manifest", "requested_targets"}
                assert "issuer.pem" not in json.dumps(run.parameters) and "initial-token" not in json.dumps(
                    run.parameters
                )
        issued = [json.loads(line) for line in (lab.home / "issued.jsonl").read_text().splitlines()]
        assert len(issued) == 5 and len({r["flow_id"] for r in issued}) == 5
        assert all(r["pid"] == first_mcp_pid for r in issued)
        assert receipt["worker_pid"] == writes[0][0]
        assert len({os.getpid(), first_mcp_pid, process.pid, lab.process.pid, writes[0][0]}) == 5
        print(
            "HTTP_WORKER_RELEASE_PASS: "
            + json.dumps(
                {
                    "flows": len(runs),
                    "issuer_deliveries": len(issued),
                    "provider_writes": len(writes),
                    "response_seconds": round(response_seconds, 2),
                    "completion_seconds": round(elapsed, 2),
                    "flow_id": str(flow_id),
                    "worker_pid": writes[0][0],
                    "mcp_before": first_mcp_pid,
                    "mcp_after": process.pid,
                    "process_worker_pid": lab.process.pid,
                }
            ),
            flush=True,
        )
    finally:
        stop_http(process)
        stop_process_lab(lab)
