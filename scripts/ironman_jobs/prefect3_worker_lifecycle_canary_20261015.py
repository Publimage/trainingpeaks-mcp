"""REAL Prefect 3 server + process worker stop/restart rehearsal on CI.

Creates only temporary local server state and two mock-provider SQLite files.
It proves queued runs survive a worker outage and a LOCAL server restart.
It does NOT prove in-flight task reassignment, HA, or any 24/7 deployment.
No TPClient, TrainingPeaks credentials/calls, DO API, or production ledger.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ledger_partial_resume_canary_20261015 import (
    PREFIX, count_external, lab_paths, register, state,
)

POOL = "ironman-prefect3-isolated-worker-lab"
DEPLOYMENT = "ironman-prefect3-worker-restart-lab/resume-lab"
FLOW_ENTRYPOINT = "scripts/ironman_jobs/prefect3_worker_resume_flow_20261015.py:worker_resume_flow"
FLAG = "IRONMAN_ISOLATED_PREFECT_LAB"


def require_env() -> None:
    if os.getenv(FLAG) != "1":
        raise RuntimeError("EXPLICIT_ISOLATED_LAB_FLAG_REQUIRED")


def choose_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def prefect_cli(env: dict, *argv: str, timeout: int = 90) -> str:
    p = subprocess.run(
        [sys.executable, "-m", "prefect", *argv],
        cwd=REPO, env=env, text=True, capture_output=True,
        timeout=timeout, check=False,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"PREFECT_CLI_FAILED:{' '.join(argv[:5])}:exit={p.returncode}:"
            f"{(p.stderr or p.stdout)[-1200:]}"
        )
    return p.stdout


def start_daemon(env: dict, outfile: Path, *argv: str) -> subprocess.Popen:
    with outfile.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "prefect", *argv],
            cwd=REPO, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc


def stop_daemon(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=12)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=10)


def server_health(url: str, proc: subprocess.Popen, log: Path, timeout: int = 100) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if proc.poll() is not None:
            raise RuntimeError("PREFECT_SERVER_EXITED:" + log.read_text(errors="replace")[-1600:])
        try:
            with urllib.request.urlopen(url + "/health", timeout=2) as result:
                if result.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    raise RuntimeError("PREFECT_SERVER_START_TIMEOUT:" + log.read_text(errors="replace")[-1600:])


async def schedule_run(root: Path) -> str:
    from prefect.client.orchestration import get_client
    async with get_client() as client:
        deployment = await client.read_deployment_by_name(DEPLOYMENT)
        flow_run = await client.create_flow_run_from_deployment(
            deployment.id, parameters={"root": str(root)}
        )
        return str(flow_run.id)


async def get_run_type(identifier: str) -> str:
    from uuid import UUID
    from prefect.client.orchestration import get_client
    async with get_client() as client:
        r = await client.read_flow_run(UUID(identifier))
        return r.state.type.value


def wait_run(identifier: str, worker: subprocess.Popen, log: Path, timeout: int = 170) -> None:
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        if worker.poll() is not None:
            raise RuntimeError("WORKER_EXITED_EARLY:" + log.read_text(errors="replace")[-1300:])
        try:
            last = asyncio.run(get_run_type(identifier))
        except Exception:
            time.sleep(2)
            continue
        if last == "COMPLETED":
            return
        if last in ("FAILED", "CRASHED", "CANCELLED"):
            raise RuntimeError("FLOW_TERMINAL_FAILURE:" + str(last) + ":" +
                               log.read_text(errors="replace")[-1300:])
        time.sleep(2)
    raise RuntimeError("FLOW_NOT_COMPLETED:" + str(last) + ":" + log.read_text(errors="replace")[-1600:])


def yaml_config(root: Path) -> Path:
    file = root / "prefect-lab.yaml"
    # Repo path is local trusted checkout, never a caller-supplied value.
    # Config lives in tempdir; no deployment edits in the connected cloud.
    file.write_text(
        'prefect-version: "3.8.8"\n'
        'name: ironman-local-worker-lab\n'
        'build: []\n'
        'push: []\n'
        'pull:\n'
        '  - prefect.deployments.steps.set_working_directory:\n'
        f'      directory: "{REPO}"\n'
        'deployments:\n'
        '  - name: resume-lab\n'
        '    version: isolated-ci-only\n'
        '    tags: [ironman, isolated, no-provider]\n'
        f'    entrypoint: "{FLOW_ENTRYPOINT}"\n'
        '    work_pool:\n'
        f'      name: "{POOL}"\n',
        encoding="utf-8",
    )
    return file


def run_worker_lifecycle_lab() -> dict:
    require_env()
    with tempfile.TemporaryDirectory(prefix=PREFIX) as temp:
        root = Path(temp)
        lab_paths(root)
        register(root)
        crash = subprocess.run(
            [sys.executable, str(SCRIPTS / "ledger_partial_resume_canary_20261015.py"),
             "--crash-child", str(root)],
            cwd=REPO, capture_output=True, text=True, timeout=15, check=False,
        )
        if (crash.returncode != -signal.SIGKILL
                or "CRASH_AFTER_EXTERNAL_COMMIT_BEFORE_LEDGER_ACK" not in crash.stdout):
            raise RuntimeError("TEST_FIXTURE_NOT_CRASHED")
        initial = state(root)
        if initial["job"] != "RUNNING" or count_external(root) != 3:
            raise RuntimeError("INITIAL_PARTIAL_STATE_BAD")

        home = root / "prefect_home"
        home.mkdir(mode=0o700)
        port = choose_port()
        url = f"http://127.0.0.1:{port}/api"
        env = {**os.environ, "PREFECT_HOME": str(home),
               "PREFECT_API_URL": url,
               "PREFECT_LOGGING_LEVEL": "WARNING",
               "PREFECT_SERVER_ANALYTICS_ENABLED": "false",
               "PREFECT_CLOUD_ENABLE_ORCHESTRATION_TELEMETRY": "false",
               "PREFECT_WORKER_QUERY_SECONDS": "2",
               FLAG: "1"}
        # The CLI/worker subprocesses use env explicitly; the SDK client
        # in THIS supervising process must use the same API, otherwise
        # get_client() launches an unrelated ephemeral Prefect server.
        os.environ["PREFECT_HOME"] = str(home)
        os.environ["PREFECT_API_URL"] = url
        server_log = root / "server.log"
        worker_log = root / "worker.log"
        server2_log = root / "server_restarted.log"
        worker2_log = root / "worker_restarted.log"
        server = None
        worker = None
        try:
            server = start_daemon(env, server_log, "server", "start",
                                  "--host", "127.0.0.1", "--port", str(port))
            server_health(url, server, server_log)
            prefect_cli(env, "work-pool", "create", POOL, "--type", "process")
            cfg = yaml_config(root)
            prefect_cli(env, "--no-prompt", "deploy", "--prefect-file", str(cfg),
                        "--name", "resume-lab", timeout=120)
            # The first job remains queued while no worker is alive.
            first_id = asyncio.run(schedule_run(root))
            time.sleep(3)
            if state(root)["job"] != "RUNNING" or count_external(root) != 3:
                raise RuntimeError("JOB_RAN_WITHOUT_WORKER")
            worker = start_daemon(env, worker_log, "worker", "start", "--pool", POOL,
                                  "--type", "process", "--name", "lab-worker-a",
                                  "--limit", "1", "--install-policy", "never")
            wait_run(first_id, worker, worker_log)
            first_state = state(root)
            if (first_state["job"] != "DONE_VERIFIED" or
                    count_external(root) != 4 or first_state["events"] != 10):
                raise RuntimeError("FIRST_WORKER_RECOVERY_FAILED")
            first_pid = worker.pid
            stop_daemon(worker)
            worker = None
            # The second flow run is queued BEFORE server shutdown; the server
            # SQLite database must preserve its identity across server restart.
            second_id = asyncio.run(schedule_run(root))
            time.sleep(3)
            if state(root)["events"] != 10 or count_external(root) != 4:
                raise RuntimeError("JOB_RAN_WHILE_WORKER_DOWN")
            stop_daemon(server)
            server = None
            server = start_daemon(env, server2_log, "server", "start",
                                  "--host", "127.0.0.1", "--port", str(port))
            server_health(url, server, server2_log)
            stored = asyncio.run(get_run_type(second_id))
            if stored not in ("SCHEDULED", "PENDING", "LATE"):
                raise RuntimeError("PENDING_FLOW_LOST_ON_SERVER_RESTART:" + str(stored))
            worker = start_daemon(env, worker2_log, "worker", "start", "--pool", POOL,
                                  "--type", "process", "--name", "lab-worker-b",
                                  "--limit", "1", "--install-policy", "never")
            wait_run(second_id, worker, worker2_log)
            after = state(root)
            if (after["job"] != "DONE_VERIFIED" or after["events"] != 10 or
                    count_external(root) != 4 or worker.pid == first_pid):
                raise RuntimeError("WORKER_RESTART_DUPLICATED_EFFECTS")
            original_state = asyncio.run(get_run_type(first_id))
            if original_state != "COMPLETED":
                raise RuntimeError("COMPLETED_RUN_NOT_PERSISTED")
            return {
                "stage": "PREFECT3_REAL_WORKER_SERVER_RESTART_LAB_PASS",
                "server_restarted": True, "worker_restarted": True,
                "distinct_worker_pids": True,
                "pending_run_survived_server_restart": True,
                "completed_run_survived_server_restart": True,
                "first_flow_state": original_state,
                "second_flow_state": "COMPLETED",
                "mock_provider_objects": 4,
                "ledger_events_before_replay": first_state["events"],
                "ledger_events_after_replay": after["events"],
                "mock_duplicate_writes": 0,
                "trainingpeaks_writes": 0, "production_ledger_access": False,
                "github_ephemeral_runner_only": True, "deployed_to_droplet": False,
            }
        finally:
            stop_daemon(worker)
            stop_daemon(server)


if __name__ == "__main__":
    print(json.dumps(run_worker_lifecycle_lab(), sort_keys=True), flush=True)
