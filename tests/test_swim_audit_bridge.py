"""Synthetic bridge/client tests. No private identifiers or credentials."""
import asyncio
import copy
import importlib.util
import io
import json
import sys
import threading
import types
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from http.client import HTTPSConnection
from http.server import ThreadingHTTPServer
from bridge_tls_fixture import secure_bridge_server, tls_metadata
from pathlib import Path
import tempfile
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from tp_mcp.swim_audit_bridge import (
    BRIDGE_URL, ITEM_KEYS, SCHEMA, SwimAuditBridgeClient, _http_read,
    build_swim_input, validate_allowlist, validate_target,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
TARGET = {"provider": "trainingpeaks", "owner_id": "101", "resource_kind": "library_template",
          "container_id": "201", "workout_id": "301"}
ITEM = {"exerciseLibraryId": 201, "exerciseLibraryItemId": 301,
        "exerciseLibraryItemType": "WorkoutTemplate", "workoutTypeId": 1,
        "distancePlanned": 200, "structure": {"structure": []},
        "description": "not transported", "fileAttachments": "not transported"}


class FakeTP:
    def __init__(self):
        self.calls = []
        self.owner = 101
        self.libraries = [{"exerciseLibraryId": 201, "ownerId": 101},
                          {"exerciseLibraryId": 999, "ownerId": 999}]
        self.items = [copy.deepcopy(ITEM), {"exerciseLibraryItemId": 999}]
        self.rejected = False

    async def __aenter__(self):
        self.calls.append("enter")
        return self

    async def __aexit__(self, *_):
        return None

    async def _get_user_data(self):
        self.calls.append("identity")
        return {"personId": self.owner}

    async def get(self, endpoint):
        self.calls.append(endpoint)
        rows = self.libraries if endpoint.endswith("/libraries") else self.items
        return SimpleNamespace(is_error=self.rejected, data=copy.deepcopy(rows))

    def post(self, *args):
        raise AssertionError("Provider writes must be unreachable")


def execute(tp=None, target=None, allow=None):
    return asyncio.run(build_swim_input(
        {"target": target or TARGET}, [TARGET] if allow is None else allow,
        client=tp or FakeTP(), now_fn=lambda: NOW))


def test_minimal_projection_no_other_items_or_private_metadata():
    tp = FakeTP()
    original = copy.deepcopy(tp.items)
    result = execute(tp)
    assert result["schema"] == SCHEMA and result["trainingpeaks_writes"] == 0
    assert set(result["item"]) == ITEM_KEYS
    assert "not transported" not in json.dumps(result)
    assert "999" not in json.dumps(result)
    assert tp.items == original
    assert tp.calls == ["identity", "/exerciselibrary/v2/libraries",
                        "/exerciselibrary/v2/libraries/201/items"]


@pytest.mark.parametrize("allow", [[], [dict(TARGET, workout_id="302")]])
def test_unapproved_template_no_provider_reads(allow):
    tp = FakeTP()
    with pytest.raises(PermissionError):
        execute(tp, allow=allow)
    assert tp.calls == []


@pytest.mark.parametrize("key,value", [("owner_id", 101), ("workout_id", True),
    ("container_id", "0"), ("workout_id", "-1"), ("owner_id", "101/.."),
    ("resource_kind", "training_plan_workout"), ("provider", "other")])
def test_scope_and_id_types(key, value):
    with pytest.raises(ValueError):
        validate_target(dict(TARGET, **{key: value}))


@pytest.mark.parametrize("allow", [None, {}, [TARGET, TARGET], [TARGET] * 9])
def test_allowlist_shape(allow):
    with pytest.raises(ValueError):
        validate_allowlist(allow)


def test_wrong_connected_owner_stops_before_library_read():
    tp = FakeTP()
    tp.owner = 102
    with pytest.raises(PermissionError):
        execute(tp)
    assert tp.calls == ["identity"]


def test_wrong_library_owner_stops_before_item_read():
    tp = FakeTP()
    tp.libraries[0]["ownerId"] = 102
    with pytest.raises(PermissionError):
        execute(tp)
    assert len(tp.calls) == 2


@pytest.mark.parametrize("key,value", [("exerciseLibraryId", 202), ("workoutTypeId", 2),
    ("workoutTypeId", True), ("exerciseLibraryItemType", "NoteTemplate")])
def test_bad_item_identity_or_type(key, value):
    tp = FakeTP()
    tp.items[0][key] = value
    with pytest.raises(ValueError):
        execute(tp)


def test_duplicate_item_and_missing_field():
    tp = FakeTP()
    tp.items.append(copy.deepcopy(tp.items[0]))
    with pytest.raises(ValueError, match="NOT_UNIQUE"):
        execute(tp)
    tp.items.pop()
    del tp.items[0]["structure"]
    with pytest.raises(ValueError, match="FIELDS_MISSING"):
        execute(tp)


def test_unknown_provider_rejection_not_retried():
    tp = FakeTP()
    tp.rejected = True
    with pytest.raises(RuntimeError, match="READ_REJECTED"):
        execute(tp)
    assert len(tp.calls) == 2


def test_client_two_routes_each_fetches_again_no_cache():
    reads = []
    def transport(payload):
        reads.append(payload)
        return execute()
    client = SwimAuditBridgeClient(TARGET, transport=transport, now_fn=lambda: NOW)
    for path in ["/exerciselibrary/v2/libraries", "/exerciselibrary/v2/libraries/201/items"] * 2:
        result = asyncio.run(client.get(path))
        assert result.is_error is False and len(result.data) == 1
    assert len(reads) == 4
    with pytest.raises(ValueError, match="ENDPOINT_NOT_ALLOWED"):
        asyncio.run(client.get("/fitness/v6/athletes/101/workouts"))
    assert len(reads) == 4


@pytest.mark.parametrize("delta", [-61, 1])
def test_client_rejects_stale_or_future_input(delta):
    result = execute()
    result["fetched_at_utc"] = (NOW + timedelta(seconds=delta)).isoformat()
    client = SwimAuditBridgeClient(TARGET, transport=lambda _: result, now_fn=lambda: NOW)
    with pytest.raises(ValueError, match="NOT_FRESH"):
        asyncio.run(client.get("/exerciselibrary/v2/libraries"))


@pytest.mark.parametrize("key,value", [("schema", "wrong"), ("projection", "FULL"),
    ("trainingpeaks_writes", 1), ("trainingpeaks_writes", False),
    ("target", dict(TARGET, workout_id="302"))])
def test_client_rejects_false_envelope(key, value):
    result = execute()
    result[key] = value
    client = SwimAuditBridgeClient(TARGET, transport=lambda _: result, now_fn=lambda: NOW)
    with pytest.raises(ValueError):
        asyncio.run(client.get("/exerciselibrary/v2/libraries"))


@pytest.mark.parametrize("code,exception", [(401, PermissionError), (403, PermissionError),
    (302, RuntimeError), (429, RuntimeError), (500, RuntimeError),
    (424, RuntimeError), (503, ConnectionError)])
def test_http_boundary_does_not_retry_or_follow_redirect(monkeypatch, code, exception):
    import tp_mcp.swim_audit_bridge as transport
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, timeout))
            raise HTTPError(request.full_url, code, "private error", {}, io.BytesIO())
    monkeypatch.setattr(transport, "bridge_client_opener", lambda: Opener())
    with pytest.raises(exception) as failure:
        _http_read({"target": TARGET})
    assert "private error" not in str(failure.value)
    assert calls == [(BRIDGE_URL, 30)]


@pytest.fixture
def bridge(monkeypatch):
    # Load the real HTTP handler with provider functions replaced before import.
    client = types.ModuleType("tp_mcp.client")
    context = types.ModuleType("tp_mcp.client.context")
    context.athlete_override = ContextVar("test_athlete", default=None)
    metrics = types.ModuleType("tp_mcp.tools.metrics")
    workouts = types.ModuleType("tp_mcp.tools.workouts")
    async def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected provider access")
    metrics.tp_get_metrics = forbidden
    workouts.tp_get_workout = workouts.tp_get_workouts = forbidden
    for name, module in [("tp_mcp.client", client), ("tp_mcp.client.context", context),
                         ("tp_mcp.tools.metrics", metrics), ("tp_mcp.tools.workouts", workouts)]:
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).parents[1] / "src/tp_mcp/private_bridge.py"
    spec = importlib.util.spec_from_file_location("isolated_bridge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tp = FakeTP()
    client.TPClient = lambda: tp
    return module, tp


def config():
    return {"host": "10.0.0.1", "port": 8787, "allowed_sources": ["127.0.0.1"],
            "allowed_athletes": ["101"], "result_writer_sources": ["127.0.0.1"],
            "max_window_days": 21, "allowed_swim_templates": [TARGET]}


@contextmanager
def server(bridge, cfg):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._handler_factory(cfg))
    temporary = tempfile.TemporaryDirectory()
    tls = secure_bridge_server(httpd, cfg, Path(temporary.name))
    if cfg.get("result_writer_sources"):
        next(iter(cfg["tls"]["peers"].values()))["result_writer"] = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_port, tls.context
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
        temporary.cleanup()


def request(port, method="POST", path="/v1/swim-audit-input", payload=None):
    port, context = port
    connection = HTTPSConnection("127.0.0.1", port, context=context, timeout=3)
    body = json.dumps({"target": TARGET} if payload is None else payload)
    try:
        connection.request(method, path, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_real_http_handler_serves_only_allowed_template(bridge):
    module, tp = bridge
    with server(module, config()) as port:
        status, result = request(port)
    assert status == 200 and result["schema"] == SCHEMA
    assert result["item"]["exerciseLibraryItemId"] == 301
    assert len(tp.calls) == 4


@pytest.mark.parametrize("change", ["disabled", "other_template", "wrong_source"])
def test_real_http_denials_have_zero_provider_access(bridge, change):
    module, tp = bridge
    cfg = config()
    if change == "disabled":
        cfg.pop("allowed_swim_templates")
    elif change == "other_template":
        cfg["allowed_swim_templates"] = [dict(TARGET, workout_id="302")]
    else:
        cfg["allowed_sources"] = ["10.0.0.99"]
    with server(module, cfg) as port:
        status, result = request(port)
    assert status == 403 and tp.calls == []


def test_health_radar_and_admin_routes_are_preserved(bridge, tmp_path):
    module, tp = bridge
    async def radar(**kwargs):
        return {"schema": "SYNTHETIC_RADAR", **kwargs}
    module._build_radar_input = radar
    module.RADAR_RESULT_DIR = tmp_path / "radar"
    with server(module, config()) as port:
        assert request(port, "GET", "/health")[0] == 200
        status, result = request(port, path="/v1/radar-input", payload={
            "athlete_id": "101", "start_date": "2026-01-01", "end_date": "2026-01-02"})
        assert status == 200 and result["schema"] == "SYNTHETIC_RADAR"
        status, _ = request(port, path="/v1/radar-result", payload={
            "schema": "IRONMAN_COACHING_RADAR_V1", "athlete_id": "101",
            "as_of": "2026-01-01", "trainingpeaks_writes": 0})
        assert status == 200
        assert request(port, path="/v1/execute")[0] == 404
    assert tp.calls == []
    assert module.ADMIN_OPERATIONS == {"status", "deploy_coaching_radar"}


def test_config_default_off_and_invalid_allowlist_fails(bridge, tmp_path):
    module, _ = bridge
    cfg = config()
    cfg["allowed_sources"] = cfg["result_writer_sources"] = ["10.0.0.2"]
    cfg.pop("allowed_swim_templates")
    path = tmp_path / "config.json"
    cfg["tls"]=tls_metadata()
    path.write_text(json.dumps(cfg)); path.chmod(0o600)
    assert module._load_config(path)["allowed_swim_templates"] == []
    cfg["allowed_swim_templates"] = [dict(TARGET, workout_id="../x")]
    cfg["tls"]=tls_metadata()
    path.write_text(json.dumps(cfg)); path.chmod(0o600)
    with pytest.raises(module.BridgeConfigError):
        module._load_config(path)


def test_unknown_provider_rejection_http_is_not_retryable(bridge):
    module, tp = bridge
    tp.rejected = True
    with server(module, config()) as port:
        status, result = request(port)
    assert status == 424 and result["error"] == "SWIM_READER_REJECTED"
    assert len(tp.calls) == 3  # enter, identity, single libraries read


def test_existing_no_store_header_is_preserved(bridge):
    module, _ = bridge
    with server(module, config()) as port:
        port, context = port
        connection = HTTPSConnection("127.0.0.1", port, context=context, timeout=3)
        connection.request("GET", "/health")
        response = connection.getresponse()
        assert response.getheader("Cache-Control") == "no-store"
        response.read()
        connection.close()
