"""Offline contract tests for the existing private VPC bridge's unified reads.

All data is synthetic. No TrainingPeaks credentials or external network.
"""
import asyncio
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from tp_mcp.private_bridge import BridgeConfigError, _handler_factory, _load_config
from tp_mcp.unified_read_bridge import (
    READ_PATH, PrivateBridgeReadAdapter, authorize, build_private_read,
    validate_policy, validate_spec,
)

OWNER = 2116886


def spec(kind="plan.workout.patch", container=684602, item=3996858792):
    return {"kind": kind, "target": {
        "provider": "trainingpeaks", "owner_id": OWNER,
        "container_kind": "workout_library" if kind.startswith("library.") else "training_plan",
        "container_id": container, "resource_id": item,
    }}


def policy(kinds=None, container=684602, container_kind="training_plan",
           resource_ids=None):
    if resource_ids is None:
        resource_ids = [3996858792, 1, 2]
    return [{"provider": "trainingpeaks", "owner_id": OWNER,
             "container_kind": container_kind, "container_id": container,
             "kinds": kinds or ["plan.workout.patch"],
             "resource_ids": resource_ids}]


def test_default_absent_config_is_deny_by_default(tmp_path):
    p=tmp_path/"private.json"
    p.write_text(json.dumps({
        "host": "10.114.0.2", "port": 8787,
        "allowed_sources": ["10.114.0.3"],
        "allowed_athletes": ["111"],
        "result_writer_sources": ["10.114.0.3"],
        "max_window_days": 21,
    }))
    cfg=_load_config(p)
    assert cfg["allowed_unified_reads"] == []


def test_invalid_unified_allowlist_reports_specific_config_error(tmp_path):
    p = tmp_path / "private.json"
    p.write_text(json.dumps({
        "host": "10.114.0.2", "port": 8787,
        "allowed_sources": ["10.114.0.3"],
        "allowed_athletes": ["111"],
        "result_writer_sources": ["10.114.0.3"],
        "max_window_days": 21,
        "allowed_unified_reads": [{
            "provider": "trainingpeaks", "owner_id": OWNER,
            "container_kind": "training_plan", "container_id": 684602,
            "kinds": ["library.workout.patch"],
            "resource_ids": [3996858792],
        }],
    }))
    with pytest.raises(BridgeConfigError, match="INVALID_UNIFIED_READ_ALLOWLIST"):
        _load_config(p)


def test_explicit_plan_allowlist_works_without_per_week_job():
    allowed=validate_policy(policy(kinds=[
        "plan.workout.patch", "plan.note.patch", "plan.note.attachment.retire",
        "plan.note.attachment.add", "plan.strength.relocate",
    ]))
    assert authorize(spec("plan.workout.patch", item=1), allowed)
    assert authorize(spec("plan.note.attachment.retire", item=2), allowed)
    with pytest.raises(PermissionError, match="UNIFIED_RESOURCE_NOT_ALLOWED"):
        authorize(spec("plan.workout.patch", item=3), allowed)
    with pytest.raises(PermissionError, match="UNIFIED_RESOURCE_NOT_ALLOWED"):
        authorize(spec("library.workout.patch", container=3891872, item=5), allowed)
    with pytest.raises(PermissionError, match="UNIFIED_RESOURCE_NOT_ALLOWED"):
        authorize(spec("plan.workout.patch", container=685173, item=5), allowed)


def test_bad_spec_or_policy_rejected_before_provider_read():
    s=spec()
    s["target"]["owner_id"] = 0
    with pytest.raises(ValueError, match="UNIFIED_PROVIDER_OWNER"):
        validate_spec(s)
    s=spec()
    s["target"]["container_kind"]="athlete_calendar"
    with pytest.raises(ValueError, match="UNIFIED_CONTAINER_KIND"):
        validate_spec(s)
    bad=policy()
    bad[0]["kinds"]=["plan.workout.patch", "plan.workout.patch"]
    with pytest.raises(ValueError, match="UNIFIED_POLICY_KINDS"):
        validate_policy(bad)


@pytest.mark.parametrize("resource_ids", [[], [0], [1, 1], ["1"], [True]])
def test_policy_rejects_missing_invalid_or_duplicate_resource_ids(resource_ids):
    with pytest.raises(ValueError, match="UNIFIED_POLICY_RESOURCE_IDS"):
        validate_policy(policy(resource_ids=resource_ids))


def test_policy_must_include_exact_resource_ids():
    bad = policy()
    del bad[0]["resource_ids"]
    with pytest.raises(ValueError, match="UNIFIED_POLICY_FIELDS"):
        validate_policy(bad)


def test_kind_projection_drops_unapproved_top_level_fields():
    from tp_mcp.unified_read_bridge import project_read_record
    native = {"workoutId": 1, "title": "Synthetic",
              "distancePlanned": 2500, "internalOnly": "do-not-forward",
              "structure": {"structure": [{"name": "300 warmup", "length": 300}]},
              "downloadUrl": "https://forbidden.invalid/private"}
    out = project_read_record(native, kind="plan.workout.patch")
    assert out["workoutId"] == 1
    assert out["distancePlanned"] == 2500
    assert out["structure"]["structure"][0]["length"] == 300
    assert "internalOnly" not in out and "downloadUrl" not in out


def test_native_library_projection_preserves_provider_identity_builder_and_planned_fields():
    from tp_mcp.unified_read_bridge import project_read_record
    native = {
        "exerciseLibraryId": 3891872,
        "exerciseLibraryItemId": 14963420,
        "exerciseLibraryItemType": "WorkoutTemplate",
        "itemName": "Test | CSS 400+200 - 2200 m",
        "workoutTypeId": 1,
        "workoutSubTypeId": None,
        "distancePlanned": 2200.0,
        "totalTimePlanned": 0.9166666666667,
        "caloriesPlanned": None,
        "tssPlanned": None,
        "ifPlanned": None,
        "velocityPlanned": None,
        "energyPlanned": None,
        "elevationGainPlanned": None,
        "description": "Synthetic library record",
        "coachComments": None,
        "fileAttachments": "https://signed.invalid/private",
        "fromLegacy": False,
        "structure": {
            "structure": [{"name": "400 warm up", "length": {"value": 400, "unit": "meter"}}],
            "polyline": [{"x": 0, "y": 1}],
        },
        "accessToken": "must-not-cross-vpc",
    }
    out = project_read_record(native, kind="library.workout.patch")
    assert out["itemName"] == native["itemName"]
    assert out["exerciseLibraryItemType"] == "WorkoutTemplate"
    assert out["workoutTypeId"] == 1
    assert out["distancePlanned"] == 2200
    assert out["fromLegacy"] is False
    assert out["structure"] == native["structure"]
    assert "fileAttachments" not in out
    assert "accessToken" not in out


def test_native_strength_projection_preserves_blocks_and_strips_secret_links():
    from tp_mcp.unified_read_bridge import project_read_record
    native = {
        "id": 33973536, "calendarId": 6678583,
        "workoutType": "StructuredStrength",
        "prescribedDurationInSeconds": 2700,
        "blocks": [{
            "type": "WarmUp",
            "exercises": [{"name": "Squat", "sets": [{"reps": 6, "rpe": 6}],
                           "signedUrl": "https://signed.invalid/secret"}],
        }],
        "clientSecret": "must-not-cross-vpc",
    }
    out = project_read_record(native, kind="plan.strength.relocate")
    assert out["blocks"][0]["exercises"][0]["sets"][0]["reps"] == 6
    assert out["prescribedDurationInSeconds"] == 2700
    assert "signedUrl" not in out["blocks"][0]["exercises"][0]
    assert "clientSecret" not in out


def test_provider_is_never_called_for_unapproved_plan():
    touched=[]
    async def reader(x):
        touched.append(x)
        return {"id": x["target"]["resource_id"]}
    with pytest.raises(PermissionError):
        asyncio.run(build_private_read({"spec": spec()}, [], read_item=reader))
    assert touched==[]
    out=asyncio.run(build_private_read(
        {"spec":spec()},policy(),read_item=reader))
    assert out["schema"] == "IRONMAN_UNIFIED_PRIVATE_READ_V1"
    assert out["trainingpeaks_writes"] == 0
    assert out["record"]["id"] == 3996858792
    assert len(touched)==1


def test_policy_opt_in_never_enables_url_or_command_input():
    s=spec()
    s["target"]["url"]="https://evil.example"
    with pytest.raises(ValueError,match="UNIFIED_TARGET_FIELDS"):
        authorize(s,policy())
    with pytest.raises(ValueError,match="UNIFIED_REQUEST_FIELDS"):
        asyncio.run(build_private_read({"spec":spec(),"shell":"id"},policy()))


def test_http_endpoint_requires_existing_vpc_source_and_explicit_plan(monkeypatch):
    import tp_mcp.private_bridge as bridge
    read_calls=[]
    async def read(payload, cfg):
        read_calls.append(payload)
        return await build_private_read(payload, cfg["allowed_unified_reads"],
                                        read_item=lambda spec: _fake_async(spec))
    monkeypatch.setattr(bridge,"_build_unified_resource_input",read)
    cfg={
        "allowed_sources":{"127.0.0.1"},
        "allowed_unified_reads":policy(),
        "allowed_athletes":set(),
        "result_writer_sources":set(),
        "max_window_days":21,
    }
    server=ThreadingHTTPServer(("127.0.0.1",0), _handler_factory(cfg))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        conn=HTTPConnection("127.0.0.1",server.server_address[1],timeout=5)
        conn.request("POST",READ_PATH,json.dumps({"spec":spec()}),
                     {"Content-Type":"application/json"})
        response=conn.getresponse()
        body=json.loads(response.read())
        assert response.status==200
        assert body["record"]["title"]=="synthetic"
        assert body["trainingpeaks_writes"]==0
        assert len(read_calls)==1
        conn.close()
        conn=HTTPConnection("127.0.0.1",server.server_address[1],timeout=5)
        conn.request("POST",READ_PATH,json.dumps({"spec":spec(container=999999)}),
                     {"Content-Type":"application/json"})
        response=conn.getresponse()
        body=json.loads(response.read())
        assert response.status==403
        assert body["error"]=="UNIFIED_RESOURCE_NOT_ALLOWED"
        # Rejected before provider read.
        assert len(read_calls)==2  # transport handler called; provider reader was not
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


async def _fake_async(spec):
    return {"title":"synthetic","id":spec["target"]["resource_id"]}



def test_never_forward_credentials_or_signed_attachment_links():
    from tp_mcp.unified_read_bridge import project_read_record
    native={
        "id":77,"description":"normal session", "accessToken":"do-not-forward",
        "inner":{"refresh_token":"do-not-forward","plannedSeconds":1800},
        "attachments":[{"id":22,"fileName":"guide.pdf",
                        "downloadUrl":"https://file.example/private?token=secret",
                        "contentLength":1024}],
    }
    safe=project_read_record(native)
    serialized=json.dumps(safe)
    assert "do-not-forward" not in serialized
    assert "https://file.example" not in serialized
    assert safe["attachments"]==[{"id":22,"fileName":"guide.pdf","contentLength":1024}]
    assert safe["inner"]["plannedSeconds"]==1800


def test_prefect_private_client_rejects_wrong_scope_returned_by_bridge(monkeypatch):
    from tp_mcp import unified_read_bridge as transport
    original=spec()
    bad={"schema":transport.SCHEMA,"kind":"plan.note.patch",
         "target":original["target"],"record":{"id":42},"trainingpeaks_writes":0}
    class Response:
        status=200
        def __enter__(self): return self
        def __exit__(self,*args): return None
        def read(self,size): return json.dumps(bad).encode()
    class Opener:
        def open(self,request,timeout): return Response()
    monkeypatch.setattr(transport, "build_opener",lambda *args:Opener())
    with pytest.raises(ValueError,match="UNIFIED_BRIDGE_RESPONSE_MISMATCH"):
        transport._remote_read(original)



def test_existing_bridge_ip_boundary_rejects_vpc_unauthorized_source(monkeypatch):
    import tp_mcp.private_bridge as bridge
    calls=[]
    async def forbidden(*args):
        calls.append(args)
        raise AssertionError("PROVIDER_MUST_NOT_BE_REACHED")
    monkeypatch.setattr(bridge, "_build_unified_resource_input", forbidden)
    cfg={
        "allowed_sources":{"10.114.0.3"},
        "allowed_unified_reads":policy(),
        "allowed_athletes":set(),
        "result_writer_sources":set(),
        "max_window_days":21,
    }
    server=ThreadingHTTPServer(("127.0.0.1",0),_handler_factory(cfg))
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        conn=HTTPConnection("127.0.0.1",server.server_address[1],timeout=5)
        conn.request("POST",READ_PATH,json.dumps({"spec":spec()}),
                     {"Content-Type":"application/json"})
        response=conn.getresponse()
        out=json.loads(response.read())
        assert response.status==403
        assert out["error"]=="SOURCE_NOT_ALLOWED"
        assert calls==[]
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize("category", ["security", "temporary", "other"])
def test_private_bridge_preserves_provider_failure_category_without_details(monkeypatch, category):
    import tp_mcp.private_bridge as bridge
    import tp_mcp.unified_read_bridge as transport
    from scripts.ironman_jobs.ironman_unified_changeset_engine import ChangeStop, SecurityDenied

    exception = {"security": SecurityDenied, "temporary": ConnectionError, "other": ChangeStop}[category]

    async def provider_denied(payload, config):
        raise exception("synthetic-private-detail")

    monkeypatch.setattr(bridge, "_build_unified_resource_input", provider_denied)
    cfg = {"allowed_sources": {"127.0.0.1"}, "allowed_unified_reads": policy(),
           "allowed_athletes": set(), "result_writer_sources": set(), "max_window_days": 21}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_factory(cfg))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Synthetic loopback server only; production URL and VPC policy stay fixed.
    monkeypatch.setattr(transport, "READ_URL", f"http://127.0.0.1:{server.server_address[1]}{READ_PATH}")
    try:
        with pytest.raises(exception) as failure:
            PrivateBridgeReadAdapter().read(spec())
        assert isinstance(failure.value, SecurityDenied) is (category == "security")
        assert "synthetic-private-detail" not in str(failure.value)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
