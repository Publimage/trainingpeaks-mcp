"""Offline regression tests for one shared native PDF uploader (plan + athlete).

Synthetic API only; no TrainingPeaks network calls or production write.
"""
from __future__ import annotations

import copy
import hashlib
from types import SimpleNamespace

import pytest

from tp_mcp.tools import plan_attachments as pdf


BLOB = b"%PDF-1.4\n" + b"synthetic-offline-only" * 20
SHA = hashlib.sha256(BLOB).hexdigest()
URL = "https://sdmntpr-test.oaiusercontent.com/files/123e4567-e89b-12d3-a456-426614174000/raw?token=opaque"
DATE = "2026-11-23"
TITLE = "READ ME FIRST | Come leggere gli allenamenti"


class FakeSource:
    def __init__(self, **kwargs):
        assert kwargs.get("follow_redirects") is False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        assert url == URL
        return SimpleNamespace(status_code=200, content=BLOB)


class FakeTP:
    def __init__(self, target_type="athlete", roster=True, source_has_file=False):
        self.target_type = target_type
        self.roster = roster
        self.calls = 0
        self.note = {
            "id": 101273446, "title": TITLE,
            "description": "Original instructions",
            "noteDate": DATE + "T00:00:00",
            "attachments": [],
        }
        if source_has_file:
            self.note["attachments"].append({
                "id": 9999, "fileName": "readme.pdf", "contentLength": len(BLOB),
            })
        self.plan = {
            "planId": 689369, "title": "Example Plan",
            "startDate": DATE, "weekCount": 8, "dayCount": 56,
            "workoutCount": 74, "isPublic": False, "price": None,
        }
        self.base_url = "https://tpapi.trainingpeaks.com"
        self._client = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def _get_user_data(self):
        return {
            "personId": pdf.OWNER,
            "athletes": ([{"athleteId": 6757136, "firstName": "Andrea",
                           "lastName": "Della Tommasina"}] if self.roster else []),
        }

    async def get(self, path):
        if path == "/users/v3/user":
            return SimpleNamespace(is_error=False, data={
                "user": {
                    "personId": pdf.OWNER,
                    "athletes": ([{"athleteId": 6757136, "firstName": "Andrea",
                                   "lastName": "Della Tommasina"}] if self.roster else []),
                }
            })
        if path == "/plans/v1/plans":
            return SimpleNamespace(is_error=False, data=[copy.deepcopy(self.plan)])
        if path == "/plans/v1/plans/689369":
            return SimpleNamespace(is_error=False, data=copy.deepcopy(self.plan))
        if path.startswith("/plans/v1/plans/689369/calendarNote/"):
            return SimpleNamespace(is_error=False, data=[copy.deepcopy(self.note)])
        if path.startswith("/fitness/v2/athletes/6757136/calendarNote/"):
            return SimpleNamespace(is_error=False, data=[copy.deepcopy(self.note)])
        if path == "/fitness/v1/athletes/6757136/calendarNote/101273446":
            return SimpleNamespace(is_error=False, data=copy.deepcopy(self.note))
        return SimpleNamespace(is_error=True, data=None)

    async def _ensure_client(self):
        return None

    async def _ensure_access_token(self):
        return SimpleNamespace(success=True)

    def _get_headers(self):
        return {"Authorization": "Bearer synthetic"}

    async def request(self, method, url, headers, json, timeout):
        assert method == "POST" and timeout == 60
        assert url.endswith("/calendarNote/101273446/attachments")
        assert json["noteId"] == 101273446 and json["fileName"] == "readme.pdf"
        assert json["contentType"] == "application/pdf"
        assert ("athleteId" if self.target_type == "athlete" else "planId") in json
        assert "data" in json
        self.calls += 1
        self.note["attachments"].append({
            "id": 50000 + self.calls, "fileName": "readme.pdf",
            "contentLength": len(BLOB),
        })
        return SimpleNamespace(status_code=201)


def params(target_type):
    return {
        "target_type": target_type,
        "target_id": 6757136 if target_type == "athlete" else 689369,
        "note_id": 101273446,
        "file_name": "readme.pdf",
        "source_url": URL,
        "expected_sha256": SHA,
        "expected_size_bytes": len(BLOB),
        "expected_note_title": TITLE,
        "expected_note_date": DATE,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["plan", "athlete"])
async def test_shared_upload_and_repeat_is_idempotent(monkeypatch, scope):
    fake = FakeTP(target_type=scope)
    monkeypatch.setattr(pdf, "TPClient", lambda: fake)
    monkeypatch.setattr(pdf.httpx, "AsyncClient", FakeSource)
    first = await pdf.tp_attach_native_note_pdf(**params(scope))
    assert first["success"] is True and first["readback_verified"] is True, first
    assert first["attachment_id"] == 50001 and fake.calls == 1
    second = await pdf.tp_attach_native_note_pdf(**params(scope))
    assert second["already_present"] is True and fake.calls == 1


@pytest.mark.asyncio
async def test_athlete_not_in_roster_is_blocked(monkeypatch):
    fake = FakeTP(roster=False)
    monkeypatch.setattr(pdf, "TPClient", lambda: fake)
    result = await pdf.tp_attach_native_note_pdf(**params("athlete"))
    assert result["error_code"] == "PROTECTED_RESOURCE" and fake.calls == 0


@pytest.mark.asyncio
async def test_wrong_athlete_note_title_is_blocked(monkeypatch):
    fake = FakeTP()
    monkeypatch.setattr(pdf, "TPClient", lambda: fake)
    request = params("athlete")
    request["expected_note_title"] = "A different note"
    result = await pdf.tp_attach_native_note_pdf(**request)
    assert result["error_code"] == "CONFLICT" and fake.calls == 0


@pytest.mark.asyncio
async def test_wrong_hash_is_blocked_before_post(monkeypatch):
    fake = FakeTP()
    monkeypatch.setattr(pdf, "TPClient", lambda: fake)
    monkeypatch.setattr(pdf.httpx, "AsyncClient", FakeSource)
    request = params("athlete")
    request["expected_sha256"] = "0" * 64
    result = await pdf.tp_attach_native_note_pdf(**request)
    assert result["error_code"] == "SOURCE_MISMATCH" and fake.calls == 0


@pytest.mark.asyncio
async def test_filename_conflict_never_overwrites(monkeypatch):
    fake = FakeTP(source_has_file=True)
    fake.note["attachments"][0]["contentLength"] = len(BLOB) + 1
    monkeypatch.setattr(pdf, "TPClient", lambda: fake)
    result = await pdf.tp_attach_native_note_pdf(**params("athlete"))
    assert result["error_code"] == "CONFLICT" and fake.calls == 0


@pytest.mark.asyncio
async def test_old_plan_tool_remains_compatible(monkeypatch):
    fake = FakeTP(target_type="plan")
    monkeypatch.setattr(pdf, "TPClient", lambda: fake)
    monkeypatch.setattr(pdf.httpx, "AsyncClient", FakeSource)
    result = await pdf.tp_attach_training_plan_note_pdf(
        plan_id=689369, note_id=101273446, file_name="readme.pdf",
        source_url=URL, expected_sha256=SHA, expected_size_bytes=len(BLOB),
    )
    assert result["success"] is True and result["plan_id"] == 689369, result


@pytest.mark.parametrize("target,expected", [
    ({"target_type": "unknown"}, "VALIDATION_ERROR"),
    ({"target_id": -1}, "VALIDATION_ERROR"),
    ({"source_url": "https://evil.example/readme.pdf"}, "PROTECTED_RESOURCE"),
])
@pytest.mark.asyncio
async def test_reject_bad_scope_id_or_untrusted_url_without_provider(monkeypatch, target, expected):
    class ForbiddenTP:
        def __init__(self):
            raise AssertionError("validation must stop before provider access")

    monkeypatch.setattr(pdf, "TPClient", ForbiddenTP)
    request = params("athlete")
    request.update(target)
    result = await pdf.tp_attach_native_note_pdf(**request)
    assert result["error_code"] == expected


def test_tool_registration():
    from tp_mcp.server import TOOLS, _TOOL_HANDLERS

    matching = [t for t in TOOLS if t.name == "tp_attach_native_note_pdf"]
    assert len(matching) == 1
    assert matching[0].annotations.idempotent_hint is False
    assert set(matching[0].input_schema["properties"]["target_type"]["enum"]) == {"plan", "athlete"}
    assert "tp_attach_native_note_pdf" in _TOOL_HANDLERS


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["plan", "athlete"])
async def test_delete_pdf_preview_and_verified_plan_removal(monkeypatch, scope):
    fake = FakeTP(target_type=scope, source_has_file=True)
    fake.note["attachments"][0]["contentType"] = "application/pdf"
    sibling = {"id": 9998, "fileName": "keep.pdf", "contentType": "application/pdf"}
    fake.note["attachments"].append(sibling)
    baseline = copy.deepcopy(fake.note)

    async def remove(method, path, *, _retry_on_401):
        assert method == "DELETE" and not _retry_on_401
        assert path == "/plans/v1/plans/689369/calendarNote/101273446/attachments/9999"
        fake.calls += 1
        fake.note["attachments"].pop(0)
        raise TimeoutError("response lost after deletion")

    monkeypatch.setattr(fake, "_request", remove, raising=False)
    monkeypatch.setattr(pdf, "TPClient", lambda: fake)
    request = {
        "target_type": scope, "target_id": params(scope)["target_id"],
        "note_id": 101273446, "attachment_id": 9999,
        "expected_file_name": "readme.pdf", "expected_note_date": DATE,
        "expected_note_title": TITLE,
    }
    assert (await pdf.tp_delete_native_note_pdf(**request))["dry_run"]
    assert (await pdf.tp_delete_native_note_pdf(
        **{**request, "expected_file_name": "wrong.pdf"}, dry_run=False,
    ))["error_code"] == "CONFLICT"
    assert fake.note == baseline and fake.calls == 0
    result = await pdf.tp_delete_native_note_pdf(**request, dry_run=False)
    if scope == "athlete":
        assert result["error_code"] == "ROUTE_UNVERIFIED"
        assert fake.calls == 0 and fake.note == baseline
    else:
        assert result["readback_verified"] and fake.calls == 1
        assert fake.note == {**baseline, "attachments": [sibling]}
        assert (await pdf.tp_delete_native_note_pdf(**request, dry_run=False))["error_code"] == "CONFLICT"
        assert fake.calls == 1
