"""Read-only TrainingPeaks gateway tests with a synthetic provider.

No real credentials, remote host, or provider mutation.
"""
import asyncio

import pytest

from scripts.ironman_jobs.ironman_unified_changeset_engine import SecurityDenied, VALID_KINDS
from scripts.ironman_jobs.ironman_unified_trainingpeaks_reads import (
    create_read_registry, plan_windows, read_trainingpeaks_item
)

OWNER = 2116886
PLAN = 684602
LIBRARY = 3891872
PERSON = 6678583
NOTE = 2653899
WORKOUT = 3996858792
STRENGTH = 33973536
LIB_ITEM = 14963420


def spec(kind, rid, container_id=PLAN):
    return {
        "kind": kind,
        "target": {
            "provider": "trainingpeaks", "owner_id": OWNER,
            "container_kind": "workout_library" if kind.startswith("library.") else "training_plan",
            "container_id": container_id, "resource_id": rid
        }
    }


class Response:
    is_error = False

    def __init__(self, data):
        self.data = data


class FakeTP:
    def __init__(self):
        self.reads = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def _get_user_data(self):
        return {"personId": OWNER}

    async def get(self, route):
        self.reads.append(route)
        if route == "/plans/v1/plans/684602":
            return Response({
                "planId": PLAN, "ownerPersonId": OWNER, "planPersonId": PERSON,
                "startDate": "2026-10-05T00:00:00Z", "weekCount": 24
            })
        if "/workouts/" in route:
            return Response([{
                "workoutId": WORKOUT, "title": "Torque week 2",
                "description": "3x5'", "structure": {"structure": []}
            }] if route.endswith("2026-10-05/2026-11-29") else [])
        if "/calendarNote/" in route:
            return Response([{
                "id": NOTE, "planId": PLAN, "title": "README FIRST",
                "description": "Three PDFs",
                "attachments": [{"id": 98909, "fileName": "weekly_v1.1.pdf"}]
            }])
        if route == "/exerciselibrary/v2/libraries/3891872/items":
            return Response([{
                "exerciseLibraryItemId": LIB_ITEM,
                "itemName": "CSS 2200m", "structure": {"structure": []}
            }])
        raise AssertionError("UNEXPECTED_PROVIDER_ENDPOINT:" + route)


def test_plan_windows_reused_for_all_24_weeks():
    ranges = plan_windows({"startDate": "2026-10-05", "weekCount": 24})
    assert ranges == [
        ("2026-10-05", "2026-11-29"),
        ("2026-11-30", "2027-01-24"),
        ("2027-01-25", "2027-03-21")
    ]


@pytest.mark.parametrize("kind,rid,container,expected", [
    ("plan.workout.patch", WORKOUT, PLAN, "Torque week 2"),
    ("plan.note.patch", NOTE, PLAN, "README FIRST"),
    ("plan.note.attachment.add", NOTE, PLAN, "README FIRST"),
    ("plan.note.attachment.retire", NOTE, PLAN, "README FIRST"),
    ("library.workout.patch", LIB_ITEM, LIBRARY, "CSS 2200m"),
])
def test_one_provider_read_gateway_for_five_kinds(monkeypatch, kind, rid, container, expected):
    import tp_mcp.client
    monkeypatch.setattr(tp_mcp.client, "TPClient", FakeTP)
    data = asyncio.run(read_trainingpeaks_item(spec(kind, rid, container)))
    assert expected in (data.get("title") or data.get("itemName") or "")


def test_strength_native_reader_scoped_to_plan_and_same_owner(monkeypatch):
    import tp_mcp.client
    import tp_mcp.tools.strength as strength
    import httpx

    monkeypatch.setattr(tp_mcp.client, "TPClient", FakeTP)

    async def access(_):
        return 123, "fake_test_token", None

    monkeypatch.setattr(strength, "_access", access)
    monkeypatch.setattr(strength, "_headers", lambda _: {"X-Test": "synthetic"})

    class MockHttp:
        status_code = 200

        def json(self):
            return {"data": {
                "id": STRENGTH, "calendarId": PERSON,
                "workoutType": "StructuredStrength", "title": "Strength Monday",
                "blocks": [{"type": "WarmUp"}]
            }}

    class MockAsyncHttp:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, headers):
            assert url.endswith("/rx/activity/v1/workouts/33973536")
            return MockHttp()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncHttp)
    obj = asyncio.run(read_trainingpeaks_item(spec("plan.strength.relocate", STRENGTH)))
    assert obj["id"] == STRENGTH and obj["calendarId"] == PERSON


def test_registry_is_generic_and_provider_writes_are_unavailable():
    registry = create_read_registry()
    assert set(registry) == VALID_KINDS
    with pytest.raises(SecurityDenied, match="PROVIDER_WRITER_NOT_APPROVED"):
        registry["plan.note.attachment.retire"].apply(spec("plan.note.attachment.retire", NOTE))


def test_rejects_wrong_owner_before_provider_read(monkeypatch):
    target = spec("plan.note.patch", NOTE)
    target["target"]["owner_id"] = 44
    with pytest.raises(Exception, match="PROVIDER_OWNER_MISMATCH"):
        asyncio.run(read_trainingpeaks_item(target))
