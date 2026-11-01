"""Contract tests for GoogleDocsConnectorAdapter; no external calls."""
from __future__ import annotations

import pytest
from google_docs_adapter import GoogleDocsConnectorAdapter
from guard import ProviderError


class Connector:
    def __init__(self):
        self.document_id = "doc-stage"
        self.revision = "rev-A"
        self.text = "start anchor\n"
        self.calls = []
        self.extra_tabs = []
        self.unsafe_element = None
        self.occurrences_override = None

    def get_document(self, *, document_id: str, fields: str):
        assert document_id == self.document_id
        assert "revisionId" in fields and "tabs" in fields
        contents = ([{"sectionBreak": {}}] +
                    [self.unsafe_element or {
                        "paragraph": {"elements": [{"textRun": {"content": self.text}}]}
                    }])
        return {"result": {
            "documentId": document_id, "revisionId": self.revision,
            "tabs": [{"tabId": "t.0", "body": {"content": contents}}] + self.extra_tabs,
        }}

    def batch_update_document(self, *, document_id: str, requests: list[dict],
                              write_control: dict):
        self.calls.append((document_id, requests, write_control))
        assert document_id == self.document_id
        if write_control.get("requiredRevisionId") != self.revision:
            raise ProviderError("Docs rejected stale revision")
        r = requests[0]["replaceAllText"]
        assert r["tabsCriteria"] == {"tabIds": ["t.0"]}
        assert r["containsText"]["matchCase"] is True
        a, b = r["containsText"]["text"], r["replaceText"]
        n = self.text.count(a)
        if n:
            self.text = self.text.replace(a, b)
            self.revision = "rev-B"
        return {"result": {
            "documentId": document_id, "writeControl": {"requiredRevisionId": self.revision},
            "replies": [{"replaceAllText": {
                "occurrencesChanged": n if self.occurrences_override is None else self.occurrences_override
            }}]
        }}


def test_read_text_and_revision():
    c = Connector()
    assert GoogleDocsConnectorAdapter(c).read("doc-stage").text == "start anchor\n"
    assert GoogleDocsConnectorAdapter(c).read("doc-stage").revision == "rev-A"


def test_real_connector_request_shape():
    c = Connector()
    a = GoogleDocsConnectorAdapter(c)
    a.replace_once("doc-stage", "rev-A", "anchor", "anchor updated")
    assert c.calls[0][2] == {"requiredRevisionId": "rev-A"}
    assert a.read("doc-stage").text == "start anchor updated\n"


def test_stale_revision_stops_write():
    c = Connector()
    with pytest.raises(ProviderError):
        GoogleDocsConnectorAdapter(c).replace_once("doc-stage", "wrong", "anchor", "updated")
    assert c.text == "start anchor\n"


def test_missing_anchor_no_verified_success():
    c = Connector()
    with pytest.raises(ProviderError, match="exactly one"):
        GoogleDocsConnectorAdapter(c).replace_once("doc-stage", "rev-A", "absent", "updated")


def test_ambiguous_anchor_no_verified_success():
    c = Connector()
    c.text = "anchor anchor\n"
    with pytest.raises(ProviderError):
        GoogleDocsConnectorAdapter(c).replace_once("doc-stage", "rev-A", "anchor", "replaced")


def test_extra_tab_ignored_without_modification():
    c = Connector()
    c.extra_tabs.append({"tabId": "t.2", "body": {"content": [{
        "paragraph": {"elements": [{"textRun": {"content": "secret other tab"}}]}}]}})
    assert "secret" not in GoogleDocsConnectorAdapter(c).read("doc-stage").text


def test_non_text_tab_element_rejected():
    c = Connector()
    c.unsafe_element = {"table": {"tableRows": []}}
    with pytest.raises(ProviderError, match="Non-paragraph"):
        GoogleDocsConnectorAdapter(c).read("doc-stage")


def test_inline_object_rejected():
    c = Connector()
    c.unsafe_element = {"paragraph": {"elements": [{"inlineObjectElement": {}}]}}
    with pytest.raises(ProviderError, match="Non-text"):
        GoogleDocsConnectorAdapter(c).read("doc-stage")


def test_wrong_document_identity_rejected():
    class Bad(Connector):
        def get_document(self, **kwargs):
            out = super().get_document(**kwargs)
            out["result"]["documentId"] = "wrong-doc"
            return out
    with pytest.raises(ProviderError, match="identity"):
        GoogleDocsConnectorAdapter(Bad()).read("doc-stage")


def test_missing_doc_tab_rejected():
    with pytest.raises(ProviderError, match="Missing or duplicate"):
        GoogleDocsConnectorAdapter(Connector(), tab_id="t.999").read("doc-stage")


def test_adapter_with_guard_full_cycle(tmp_path):
    from guard import DocsWriteGuard, Patch
    c = Connector()
    class Auth:
        def permits(self, p):
            return (p.document_id == 'doc-stage' and
                    p.approval_ref == 'approved-test' and
                    p.old == 'anchor' and p.new == 'anchor CHECKPOINT-STAGE' and
                    p.checkpoint == 'CHECKPOINT-STAGE')
    p = Patch('stage-op', 'doc-stage', 'AUTO', 'rev-A', 'anchor',
              'anchor CHECKPOINT-STAGE', 'CHECKPOINT-STAGE', 'approved-test')
    g = DocsWriteGuard(GoogleDocsConnectorAdapter(c), Auth(),
                       str(tmp_path / 'journal.db'), {'doc-stage'})
    assert g.execute(p) == 'VERIFIED'
    assert g.execute(p) == 'ALREADY_VERIFIED'
    assert len(c.calls) == 1
    assert c.calls[0][2]['requiredRevisionId'] == 'rev-A'


def test_guard_and_adapter_stale_revision_stops_external_write(tmp_path):
    from guard import DocsWriteGuard, Patch, GuardError
    c = Connector()
    class Auth:
        def permits(self, _): return True
    p = Patch('stage-op', 'doc-stage', 'AUTO', 'rev-older', 'anchor',
              'anchor CHECKPOINT-STAGE', 'CHECKPOINT-STAGE', 'approved-test')
    g = DocsWriteGuard(GoogleDocsConnectorAdapter(c), Auth(),
                       str(tmp_path / 'journal.db'), {'doc-stage'})
    with pytest.raises(GuardError, match='Stale revision'):
        g.execute(p)
    assert c.calls == []


def test_raw_google_docs_rest_contract_requires_write_control():
    class WrongResponseConnector(Connector):
        def batch_update_document(self, **kwargs):
            output = super().batch_update_document(**kwargs)
            output["result"]["revisionId"] = output["result"].pop("writeControl")["requiredRevisionId"]
            return output
    c = WrongResponseConnector()
    with pytest.raises(ProviderError, match="Google Docs writeControl"):
        GoogleDocsConnectorAdapter(c).replace_once("doc-stage", "rev-A", "anchor", "anchor UPDATED")


def test_raw_google_docs_rest_contract_rejects_empty_updated_revision():
    class EmptyRevisionConnector(Connector):
        def batch_update_document(self, **kwargs):
            output = super().batch_update_document(**kwargs)
            output["result"]["writeControl"] = {"requiredRevisionId": ""}
            return output
    c = EmptyRevisionConnector()
    with pytest.raises(ProviderError, match="Google Docs writeControl"):
        GoogleDocsConnectorAdapter(c).replace_once("doc-stage", "rev-A", "anchor", "anchor UPDATED")
