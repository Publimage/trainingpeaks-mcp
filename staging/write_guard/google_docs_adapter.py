"""Google Docs connector adapter for the IRONMAN write guard.

Production-shaped request contract, but not an authenticated production client.
The caller supplies an official Google Docs connector client implementing
get_document() and batch_update_document(). The adapter NEVER obtains tokens.

Scope deliberately narrow: replace a unique text span in one named tab whose
body consists solely of text paragraphs. Other structural elements fail closed.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from guard import Document, ProviderError


class DocsConnector(Protocol):
    def get_document(self, *, document_id: str, fields: str) -> Mapping: ...
    def batch_update_document(self, *, document_id: str, requests: list[dict],
                              write_control: dict) -> Mapping: ...


class GoogleDocsConnectorAdapter:
    FIELDS = "documentId,revisionId,tabs(tabProperties,documentTab(body(content)))"

    def __init__(self, connector: DocsConnector, *, tab_id: str = "t.0"):
        if not tab_id or not isinstance(tab_id, str):
            raise ValueError("Explicit tab ID required")
        self.connector = connector
        self.tab_id = tab_id

    @staticmethod
    def _unwrap(response: Mapping) -> Mapping:
        if not isinstance(response, Mapping):
            raise ProviderError("Invalid connector response")
        obj = response.get("result", response)
        if not isinstance(obj, Mapping):
            raise ProviderError("Invalid connector result")
        return obj

    def read(self, document_id: str) -> Document:
        root = self._unwrap(self.connector.get_document(
            document_id=document_id, fields=self.FIELDS
        ))
        if root.get("documentId") != document_id:
            raise ProviderError("Document identity mismatch")
        revision = root.get("revisionId")
        if not isinstance(revision, str) or not revision:
            raise ProviderError("Provider revision not supplied")
        tabs = root.get("tabs")
        if not isinstance(tabs, list):
            raise ProviderError("Expected native Docs tabs")
        selected = [t for t in tabs if isinstance(t, Mapping)
                    and (t.get("tabId") or t.get("tabProperties", {}).get("tabId")) == self.tab_id]
        if len(selected) != 1:
            raise ProviderError("Missing or duplicate Docs tab ID")
        tab = selected[0]
        body = tab.get("body") or tab.get("documentTab", {}).get("body")
        if not isinstance(body, Mapping) or not isinstance(body.get("content"), list):
            raise ProviderError("Document tab body unavailable")
        out = []
        for item in body["content"]:
            if "sectionBreak" in item:
                continue
            paragraph = item.get("paragraph")
            if not isinstance(paragraph, Mapping):
                raise ProviderError("Non-paragraph element outside safe adapter scope")
            for element in paragraph.get("elements", []):
                text_run = element.get("textRun")
                if not isinstance(text_run, Mapping) or not isinstance(text_run.get("content"), str):
                    raise ProviderError("Non-text inline content outside safe adapter scope")
                out.append(text_run["content"])
        return Document(revision=revision, text="".join(out))

    def replace_once(self, document_id: str, required_revision: str,
                     old: str, new: str) -> None:
        if not all(isinstance(value, str) and value for value in
                   (document_id, required_revision, old, new)):
            raise ProviderError("Incomplete Google Docs write request")
        if old == new:
            raise ProviderError("No-op replacement")
        response = self._unwrap(self.connector.batch_update_document(
            document_id=document_id,
            requests=[{
                "replaceAllText": {
                    "containsText": {"text": old, "matchCase": True},
                    "replaceText": new,
                    "tabsCriteria": {"tabIds": [self.tab_id]},
                }
            }],
            write_control={"requiredRevisionId": required_revision},
        ))
        if response.get("documentId") != document_id:
            raise ProviderError("Write response identity mismatch")
        replies = response.get("replies")
        if not isinstance(replies, list) or len(replies) != 1:
            raise ProviderError("Write response missing replacement count")
        replaced = replies[0].get("replaceAllText", {}).get("occurrencesChanged")
        if replaced != 1:
            raise ProviderError("Expected exactly one replacement from provider")
        # Native Google Docs documents.batchUpdate returns the updated revision
        # inside writeControl.requiredRevisionId (not a top-level revisionId).
        # A previous fake returned a top-level field and concealed this contract
        # mismatch until the real REST integration stage.
        updated_control = response.get("writeControl")
        updated_revision = (updated_control.get("requiredRevisionId")
                            if isinstance(updated_control, Mapping) else None)
        if not isinstance(updated_revision, str) or not updated_revision:
            raise ProviderError("Updated revision missing in Google Docs writeControl")
