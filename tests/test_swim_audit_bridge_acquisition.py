"""Synthetic end-to-end composition with the existing acquisition validators."""
import asyncio

import pytest

from tp_mcp.swim_audit_bridge import SwimAuditBridgeClient, build_swim_input
from test_swim_audit_acquisition import FakeDrive, FakeTP, NOW, fixtures, run
from scripts.ironman_jobs.swim_audit_report import payload_sha256


@pytest.mark.parametrize("case,expected", [("complete", "PASS"), ("targeted", "PARTIAL"),
                                            ("missing_pause", "FAIL")])
def test_bridge_composes_with_existing_source_and_validators(case, expected):
    request, record, item = fixtures()
    if case == "targeted":
        record["recovery"]["coverage"] = "targeted"
        request["reviewed_record_sha256"] = payload_sha256(record)
    elif case == "missing_pause":
        item["structure"]["structure"][0]["steps"].pop()
    tp = FakeTP(item)
    async def identity():
        return {"personId": int(request["target"]["owner_id"])}
    tp._get_user_data = identity
    def transport(payload):
        return asyncio.run(build_swim_input(payload, [request["target"]],
                                           client=tp, now_fn=lambda: NOW))
    client = SwimAuditBridgeClient(request["target"], transport=transport, now_fn=lambda: NOW)
    drive = FakeDrive(record)
    result = run(request, drive, client)
    assert result["status"] == expected
    assert result["provider_writes"] == 0
    assert result["external_authenticity_verified"] is False
    assert result["publishing_authorized"] is False
    assert len(drive.calls) == 2 and len(tp.calls) == 8
