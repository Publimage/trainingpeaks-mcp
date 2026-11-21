"""Evidence-only completion gates for IRONMAN connected operations.

Pure functions: no network, credentials, retries or provider mutations.
A connector response describing a write is NOT proof of a completed update.
Provider readback is supplied by the caller after the attempted operation.
This module cannot override access controls or prove that an input is genuine.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class GateResult:
    state: str
    reason: str
    checked_items: int = 0


def _text_from_paragraphs(paragraphs: Sequence[object]) -> str:
    items: list[str] = []
    for item in paragraphs:
        if isinstance(item, str):
            items.append(item)
        elif isinstance(item, Mapping) and isinstance(item.get("text"), str):
            items.append(item["text"])
        else:
            raise ValueError("INVALID_PARAGRAPH")
    return "\n".join(items)


def assess_google_doc(
    *,
    expected_document_id: str,
    readback_document_id: str,
    revision_id: str | None,
    paragraphs: Sequence[object] | None,
    required_fragments: Sequence[str],
    readback_after_attempt: bool,
    denied_by_security: bool = False,
) -> GateResult:
    """Require a fresh document readback, not a write receipt or chat summary.

    Caller must use an authenticated get_document_text after its action and
    supply its exact document ID, revision and paragraph content. This does
    not retry or suggest bypassing any denied operation.
    """
    if denied_by_security:
        return GateResult("BLOCCATA", "DENIEGO_ESPLICITO_NON_RIPETERE")
    if not expected_document_id or readback_document_id != expected_document_id:
        return GateResult("NON_VERIFICATA", "DOCUMENTO_NON_CORRISPONDENTE")
    if not readback_after_attempt or not revision_id or paragraphs is None:
        return GateResult("NON_VERIFICATA", "RILETTURA_PROVIDER_MANCANTE")
    if not required_fragments or any(not x.strip() for x in required_fragments):
        return GateResult("NON_VERIFICATA", "CRITERI_DI_VERIFICA_ASSENTI")
    try:
        whole_text = _text_from_paragraphs(paragraphs)
    except ValueError:
        return GateResult("NON_VERIFICATA", "CONTENUTO_RILETTURA_NON_VALIDO")
    missing = [frag for frag in required_fragments if frag not in whole_text]
    if missing:
        return GateResult("NON_VERIFICATA", f"CONTENUTO_MANCANTE:{len(missing)}",
                          len(required_fragments) - len(missing))
    # ALREADY present after the operation is still VERIFICATA: attribution of
    # an actual write to this session is a separate question.
    return GateResult("VERIFICATA", "CONTENUTO_PRESENTE_NEL_PROVIDER",
                      len(required_fragments))


def assess_tp_publisher_report(
    *,
    expected_plan_id: int,
    expected_manifest_sha256: str,
    expected_target_count: int,
    report: Mapping[str, object] | None,
    denied_by_security: bool = False,
) -> GateResult:
    """Cross-check the existing reviewed publisher's final report.

    This is NOT a replacement for its own native provider GET/readback and
    non-target diff. It rejects previews and unverified/foreign reports.
    """
    if denied_by_security:
        return GateResult("BLOCCATA", "DENIEGO_ESPLICITO_NON_RIPETERE")
    if report is None:
        return GateResult("NON_VERIFICATA", "REPORT_PROVIDER_ASSENTE")
    if report.get("stage") != "PLAN_PATCH_PUBLISH_VERIFIED":
        return GateResult("NON_VERIFICATA", "PUBLISH_NON_VERIFICATO")
    if (report.get("plan") != expected_plan_id
            or report.get("manifest_sha256") != expected_manifest_sha256
            or report.get("targets") != expected_target_count):
        return GateResult("NON_VERIFICATA", "SCOPE_O_MANIFEST_NON_CORRISPONDENTE")
    if report.get("readback_verified") is not True:
        return GateResult("NON_VERIFICATA", "RILETTURA_PROVIDER_MANCANTE")
    if (report.get("athlete_calendar_writes") != 0
            or report.get("library_writes") != 0):
        return GateResult("NON_VERIFICATA", "SCRITTURE_ESTRANEE_ALLO_SCOPE")
    return GateResult("VERIFICATA", "PUBLISHER_VERIFICATO",
                      expected_target_count)
