"""Offline cross-plan parity for ONE native PDF retirement adapter.

These are not TrainingPeaks writes. They intentionally exercise one adapter
with multiple independent plan IDs, notes and attachment IDs.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    Ledger, SecurityDenied, digest, run_changeset,
)
from scripts.ironman_jobs.ironman_unified_note_pdf_adapter import (
    ReviewedNotePdfRetireAdapter, proven_path_delete_one_pdf,
)

OWNER = 2116886
REV = "a" * 40
SCOPE = "approved:offline-parity-only"


class FakeProvider:
    def __init__(self, notes):
        self.notes = deepcopy(notes)
        self.writes = []
        self.fail = None

    def read(self, item):
        target = item["target"]
        return deepcopy(self.notes[(target["container_id"], target["resource_id"])])

    def delete_one(self, plan_id, note_id, pdf_id):
        key = (plan_id, note_id)
        self.writes.append((plan_id, note_id, pdf_id))
        if self.fail == "deny":
            raise SecurityDenied("SYNTHETIC_DENIAL")
        if self.fail == "timeout_before":
            raise TimeoutError("synthetic uncertain result")
        note = self.notes[key]
        note["attachments"] = [a for a in note["attachments"] if a["id"] != pdf_id]
        if self.fail == "timeout_after":
            raise TimeoutError("synthetic committed then connection lost")


def note(plan, note_id, obsolete, *, good=777):
    return {
        "id": note_id, "planId": plan,
        "title": "README FIRST", "description": "Athlete information and links",
        "attachments": [
            {"id": obsolete, "fileName": "superseded.pdf", "contentLength": 169368, "contentType": "application/pdf"},
            {"id": good, "fileName": "current.pdf", "contentLength": 109724, "contentType": "application/pdf"},
        ],
    }


def entry(name, plan, note_id, before, pdf_id, *, desired=None, depends=None):
    if desired is None:
        desired = deepcopy(before)
        desired["attachments"] = [a for a in desired["attachments"] if a["id"] != pdf_id]
    original = next(a for a in before["attachments"] if a["id"] == pdf_id)
    return {
        "id": name,
        "kind": "plan.note.attachment.retire",
        "target": {"provider": "trainingpeaks", "owner_id": OWNER,
                   "container_kind": "training_plan",
                   "container_id": plan, "resource_id": note_id},
        "before_sha256": digest(before),
        "after_sha256": digest(desired),
        "depends_on": depends or [],
        "payload": {"desired": desired, "attachment_id": pdf_id,
                    "expected_file_name": original["fileName"],
                    "expected_content_length": original["contentLength"]},
    }


def manifest(*changes):
    return {"schema": "IRONMAN_CHANGESET_V1", "request_id": "offline-cross-plan-001",
            "owner_id": OWNER, "reviewed_revision": REV,
            "approval_scope": SCOPE, "changes": list(changes)}


def run(m, provider, tmp_path, *, execute=False, writer=True):
    db = Ledger(tmp_path / "pdf-ledger.sqlite3")
    try:
        adapter = ReviewedNotePdfRetireAdapter(
            reader=provider, delete_one=provider.delete_one if writer else None,
        )
        return run_changeset(
            m, {"plan.note.attachment.retire": adapter}, db,
            execute=execute,
            reviewed_revision=REV if execute else None,
            approval_scope=SCOPE if execute else None,
        )
    finally:
        db.close()


def test_one_adapter_two_independent_plans_preview_execute_resume(tmp_path):
    # The same class accepts unrelated plan/note/PDF IDs, never a new job.
    a, b = note(684602, 2653899, 95193), note(777001, 777002, 777003)
    provider = FakeProvider({(684602, 2653899): a, (777001, 777002): b})
    m = manifest(entry("intermediate", 684602, 2653899, a, 95193),
                 entry("second-plan", 777001, 777002, b, 777003))
    preview = run(m, provider, tmp_path)
    assert [x["state"] for x in preview["results"]] == ["PREFLIGHT_PASS"]*2
    assert provider.writes == []
    done = run(m, provider, tmp_path, execute=True)
    assert [x["state"] for x in done["results"]] == ["DONE_VERIFIED"]*2
    assert provider.writes == [(684602, 2653899, 95193), (777001, 777002, 777003)]
    assert provider.notes[(684602, 2653899)]["attachments"][0]["id"] == 777
    assert provider.notes[(777001, 777002)]["attachments"][0]["id"] == 777
    resumed = run(m, provider, tmp_path, execute=True)
    assert all(x["source"] == "provider_rechecked" for x in resumed["results"])
    assert len(provider.writes) == 2


def test_two_pdfs_in_same_note_serialize_via_dependencies(tmp_path):
    old = note(684602, 2653899, 95193)
    old["attachments"].append({"id": 95228, "fileName": "old-guide.pdf",
                               "contentLength": 396936, "contentType": "application/pdf"})
    intermediate = deepcopy(old)
    intermediate["attachments"] = [a for a in old["attachments"] if a["id"] != 95193]
    provider = FakeProvider({(684602, 2653899): old})
    m = manifest(entry("old-weekly", 684602, 2653899, old, 95193),
                 entry("old-guide", 684602, 2653899, intermediate, 95228,
                       depends=["old-weekly"]))
    result = run(m, provider, tmp_path, execute=True)
    assert all(x["state"] == "DONE_VERIFIED" for x in result["results"])
    assert provider.writes == [(684602, 2653899, 95193), (684602, 2653899, 95228)]
    assert [x["id"] for x in provider.notes[(684602, 2653899)]["attachments"]] == [777]


def test_no_writer_enabled_fails_closed(tmp_path):
    first = note(684602, 2653899, 95193)
    provider = FakeProvider({(684602, 2653899): first})
    m = manifest(entry("pdf", 684602, 2653899, first, 95193))
    result = run(m, provider, tmp_path, execute=True, writer=False)
    assert result["results"][0]["state"] == "BLOCKED_SECURITY"
    assert provider.writes == []


@pytest.mark.parametrize("case", ["wrong_file_name", "alter_note_body", "non_pdf", "wrong_plan"])
def test_wrong_target_or_mutated_preservation_fails_without_writes(tmp_path, case):
    first = note(684602, 2653899, 95193)
    provider = FakeProvider({(684602, 2653899): first})
    target = entry("pdf", 684602, 2653899, first, 95193)
    if case == "wrong_file_name":
        target["payload"]["expected_file_name"] = "mismatched.pdf"
    elif case == "alter_note_body":
        target["payload"]["desired"]["description"] = "BAD rewrite"
        target["after_sha256"] = digest(target["payload"]["desired"])
    elif case == "non_pdf":
        first["attachments"][0]["fileName"] = "not-a-pdf.txt"
        target["before_sha256"] = digest(first)
        target["payload"]["expected_file_name"] = "not-a-pdf.txt"
    else:
        provider.notes[(684602, 2653899)]["planId"] = 777001
        target["before_sha256"] = digest(provider.notes[(684602, 2653899)])
    m = manifest(target)
    result = run(m, provider, tmp_path, execute=True)
    assert result["results"][0]["state"] in ("FAILED_REVIEW", "BLOCKED_CONFLICT")
    assert provider.writes == []


@pytest.mark.parametrize("mode,expected", [
    ("timeout_after", "DONE_VERIFIED"),
    ("timeout_before", "UNKNOWN_NEEDS_READBACK"),
    ("deny", "BLOCKED_SECURITY"),
])
def test_ambiguous_write_never_replayed(mode, expected, tmp_path):
    first = note(684602, 2653899, 95193)
    provider = FakeProvider({(684602, 2653899): first})
    provider.fail = mode
    m = manifest(entry("pdf", 684602, 2653899, first, 95193))
    result = run(m, provider, tmp_path, execute=True)
    assert result["results"][0]["state"] == expected
    assert provider.writes == [(684602, 2653899, 95193)]


def test_proven_endpoint_is_one_delete_without_automatic_retry(monkeypatch):
    import tp_mcp.client
    seen = []

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return False
        async def _get_user_data(self):
            return {"personId": OWNER}
        async def _request(self, method, path, **kw):
            seen.append((method, path, kw))
            return type("Response", (), {"is_error": False})()

    monkeypatch.setattr(tp_mcp.client, "TPClient", FakeClient)
    asyncio.run(proven_path_delete_one_pdf(777001, 777002, 777003))
    assert seen == [("DELETE", "/plans/v1/plans/777001/calendarNote/777002/attachments/777003",
                     {"_retry_on_401": False})]