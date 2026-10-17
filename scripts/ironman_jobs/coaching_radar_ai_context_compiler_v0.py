"""Deterministic selective context compiler for Coaching Radar AI shadow mode.

No network calls and no AI calls. The compiler reduces an already verified
full Knowledge Base bundle to bounded, provenance-preserving excerpts based on
the current Radar signal classes. It is deterministic and model-agnostic.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

SCHEMA = "IRONMAN_COACHING_RADAR_AI_CONTEXT_V1"

CATEGORY_TERMS = {
    "TSS_DATA_QUALITY": (
        "tss", "threshold", "soglia", "power", "potenza", "heart rate",
        "frequenza cardiaca", "rpe", "sensor", "sensore", "data quality",
        "qualita dato", "qualità dato",
    ),
    "IF_DATA_QUALITY": (
        "if", "intensity factor", "threshold", "soglia", "rpe", "power",
        "potenza", "pace", "ritmo", "data quality", "qualita dato", "qualità dato",
    ),
    "COMPLETION_UNCONFIRMED": (
        "completion", "completed", "eseguito", "saltata", "saltato",
        "feedback", "comunicazione", "assenza", "mancante", "planned",
        "programmato",
    ),
    "DURATION_SHORT": (
        "duration", "durata", "planned", "programmato", "actual", "eseguito",
        "feedback", "rpe", "recuper", "fatica", "sostenibil",
    ),
}

GLOBAL_POLICY_TERMS = (
    "coach decide",
    "coach",
    "decisione",
    "source of truth",
    "fonte canonica",
    "trainingpeaks",
    "read_only",
    "read only",
    "evidenza",
    "incertezza",
)

DATA_ABSENCE_TERMS = (
    "assenza",
    "missing",
    "mancante",
    "feedback",
    "wellness",
    "rpe",
    "non equivale",
)

ROLE_BASE_WEIGHT = {
    "athlete_card": 7,
    "master_coaching_context": 5,
    "specialist": 4,
    "decision_log": 3,
    "open_questions_roadmap": 2,
    "workstream_state": 2,
    "core_index": 1,
}


@dataclass(frozen=True)
class Section:
    heading: str
    text: str
    ordinal: int


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def split_markdown_sections(text: str) -> list[Section]:
    """Split Markdown-ish exported Google Docs into bounded semantic sections."""
    lines = text.splitlines()
    sections: list[Section] = []
    heading = "(document start)"
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        content = "\n".join(buf).strip()
        if content:
            sections.append(Section(heading=heading, text=content, ordinal=len(sections)))
        buf = []

    for raw in lines:
        line = raw.rstrip()
        if re.match(r"^#{1,6}\s+\S", line):
            flush()
            heading = re.sub(r"^#{1,6}\s+", "", line).strip()
        else:
            buf.append(line)
    flush()

    if not sections and text.strip():
        sections = [Section(heading="(document)", text=text.strip(), ordinal=0)]
    return sections


def _terms_for_radar(radar: dict[str, Any]) -> tuple[str, ...]:
    terms: list[str] = list(GLOBAL_POLICY_TERMS)
    categories = {
        str(item.get("category") or "")
        for item in radar.get("alerts", [])
        if isinstance(item, dict)
    }
    for category in sorted(categories):
        terms.extend(CATEGORY_TERMS.get(category, (category.lower(),)))
    dq = radar.get("data_quality") or {}
    if dq.get("missing_rpe_workout_ids") or int(dq.get("wellness_metrics_count") or 0) == 0:
        terms.extend(DATA_ABSENCE_TERMS)
    for item in radar.get("alerts", []):
        if not isinstance(item, dict):
            continue
        sport = str(item.get("sport") or "").strip().lower()
        if sport:
            terms.append(sport)
    for item in radar.get("upcoming", []):
        if not isinstance(item, dict):
            continue
        sport = str(item.get("sport") or "").strip().lower()
        if sport:
            terms.append(sport)
    return tuple(dict.fromkeys(_norm(x) for x in terms if str(x).strip()))


def _term_matches(term: str, hay: str) -> bool:
    term = _norm(term)
    if not term:
        return False
    if re.fullmatch(r"[a-z0-9]+", term) and len(term) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", hay) is not None
    return term in hay


def _matched_terms(section: Section, terms: tuple[str, ...]) -> tuple[str, ...]:
    hay = _norm(section.heading + "\n" + section.text)
    return tuple(term for term in terms if _term_matches(term, hay))


def _score(section: Section, terms: tuple[str, ...], *, role: str) -> tuple[int, int, int]:
    matched = _matched_terms(section, terms)
    hits = len(matched)
    base = ROLE_BASE_WEIGHT.get("specialist" if role.startswith("specialist:") else role, 0)
    heading_hits = sum(1 for term in matched if term in _norm(section.heading))
    # Base weight breaks ties only when there is a semantic match. Required
    # sources are added separately even if no alert-specific term is present.
    score = hits * 10 + heading_hits * 5 + (base if hits else 0)
    return (score, -section.ordinal, -len(section.text))


def _source_meta(packet: dict[str, Any], role: str) -> dict[str, Any]:
    idx = packet["knowledge_base"]["source_index"]
    if role.startswith("specialist:"):
        pos = int(role.split(":", 1)[1])
        item = idx["specialist_documents"][pos]
    else:
        item = idx[role]
    return {
        "role": role,
        "title": item["title"],
        "document_id": item["document_id"],
        "source_version": item["source_version"],
        "content_sha256": item["content_sha256"],
    }


def compile_selective_context(
    input_packet: dict[str, Any],
    *,
    max_total_chars: int = 18000,
    max_excerpt_chars: int = 3200,
    max_sections_per_source: int = 2,
) -> dict[str, Any]:
    if input_packet.get("schema") != "IRONMAN_COACHING_RADAR_AI_INPUT_V1":
        raise ValueError("CONTEXT_INPUT_SCHEMA_MISMATCH")
    if input_packet.get("mode") != "SHADOW_READ_ONLY":
        raise ValueError("CONTEXT_INPUT_MODE_MISMATCH")
    if max_total_chars < 4000 or max_excerpt_chars < 500 or max_sections_per_source < 1:
        raise ValueError("CONTEXT_BUDGET_INVALID")

    kb = input_packet.get("knowledge_base")
    if not isinstance(kb, dict):
        raise ValueError("CONTEXT_KB_MISSING")
    contents = kb.get("contents")
    if not isinstance(contents, dict) or not contents:
        raise ValueError("CONTEXT_KB_CONTENTS_MISSING")

    terms = _terms_for_radar(input_packet["radar"])
    candidates: list[tuple[int, str, Section]] = []
    for role, text in contents.items():
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"CONTEXT_EMPTY_SOURCE:{role}")
        for section in split_markdown_sections(text):
            score = _score(section, terms, role=role)[0]
            candidates.append((score, role, section))

    candidates.sort(key=lambda x: (-x[0], x[1], x[2].ordinal))

    required_families = ("athlete_card", "master_coaching_context")
    selected: list[dict[str, Any]] = []
    per_source: dict[str, int] = {}
    used_chars = 0
    selected_keys: set[tuple[str, int]] = set()

    def add(role: str, section: Section, score: int) -> bool:
        nonlocal used_chars
        key = (role, section.ordinal)
        if key in selected_keys:
            return False
        if per_source.get(role, 0) >= max_sections_per_source:
            return False
        text = section.text[:max_excerpt_chars].strip()
        if not text:
            return False
        if used_chars + len(text) > max_total_chars:
            return False
        meta = _source_meta(input_packet, role)
        selected.append({
            **meta,
            "section_heading": section.heading,
            "section_ordinal": section.ordinal,
            "selection_score": score,
            "matched_terms": list(_matched_terms(section, terms)),
            "excerpt": text,
            "excerpt_sha256": _sha(text),
        })
        selected_keys.add(key)
        per_source[role] = per_source.get(role, 0) + 1
        used_chars += len(text)
        return True

    # Mandatory athlete + coaching-policy grounding.
    for required in required_families:
        role_candidates = [c for c in candidates if c[1] == required]
        if not role_candidates:
            raise ValueError(f"CONTEXT_REQUIRED_SOURCE_MISSING:{required}")
        score, role, section = role_candidates[0]
        if not add(role, section, score):
            raise ValueError(f"CONTEXT_REQUIRED_SOURCE_BUDGET:{required}")

    # At least one specialist excerpt is mandatory.
    specialist_candidates = [c for c in candidates if c[1].startswith("specialist:")]
    if not specialist_candidates:
        raise ValueError("CONTEXT_SPECIALIST_SOURCE_MISSING")
    score, role, section = specialist_candidates[0]
    if not add(role, section, score):
        raise ValueError("CONTEXT_SPECIALIST_SOURCE_BUDGET")

    for score, role, section in candidates:
        if score <= 0:
            continue
        add(role, section, score)

    categories = sorted({
        str(x.get("category"))
        for x in input_packet["radar"].get("alerts", [])
        if isinstance(x, dict) and x.get("category")
    })
    compiled = {
        "schema": SCHEMA,
        "mode": "SHADOW_READ_ONLY",
        "athlete_id": input_packet["athlete_id"],
        "as_of": input_packet["as_of"],
        "input_fingerprint_sha256": input_packet["input_fingerprint_sha256"],
        "radar_evidence_sha256": input_packet["radar"]["evidence_sha256"],
        "context_fingerprint_sha256": kb["context_fingerprint_sha256"],
        "signal_categories": categories,
        "selection_terms": list(terms),
        "excerpt_count": len(selected),
        "selected_char_count": used_chars,
        "max_total_chars": max_total_chars,
        "excerpts": selected,
        "guardrails": {
            "deterministic_selection": True,
            "full_document_forwarding": False,
            "trainingpeaks_writes_allowed": False,
            "drive_writes_allowed": False,
            "ai_calls": 0,
        },
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
    }
    digest_source = {k: v for k, v in compiled.items() if k != "compiled_fingerprint_sha256"}
    compiled["compiled_fingerprint_sha256"] = hashlib.sha256(
        json.dumps(digest_source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return compiled


def evaluate_compiled_context(
    compiled: dict[str, Any],
    *,
    expected_categories: list[str],
    expected_role_families: list[str],
    max_chars: int,
) -> dict[str, Any]:
    if compiled.get("schema") != SCHEMA:
        raise ValueError("CONTEXT_EVAL_SCHEMA_MISMATCH")
    excerpts = compiled.get("excerpts")
    if not isinstance(excerpts, list) or not excerpts:
        raise ValueError("CONTEXT_EVAL_EXCERPTS_MISSING")

    actual_categories = set(compiled.get("signal_categories") or [])
    missing_categories = sorted(set(expected_categories) - actual_categories)
    roles = {str(item.get("role") or "") for item in excerpts}
    matched_terms = {
        term
        for item in excerpts
        for term in (item.get("matched_terms") or [])
    }

    def family_hit(family: str) -> bool:
        return family in roles or (family == "specialist" and any(x.startswith("specialist:") for x in roles))

    missing_roles = [x for x in expected_role_families if not family_hit(x)]
    category_routing_misses = {}
    for category in expected_categories:
        candidates = CATEGORY_TERMS.get(category, ())
        if candidates and not any(_norm(term) in matched_terms for term in candidates):
            category_routing_misses[category] = list(candidates)

    chars = int(compiled.get("selected_char_count") or 0)
    duplicate_excerpts = len({x["excerpt_sha256"] for x in excerpts}) != len(excerpts)

    passed = (
        not missing_categories
        and not missing_roles
        and not category_routing_misses
        and chars <= max_chars
        and not duplicate_excerpts
        and compiled.get("trainingpeaks_writes") == 0
        and compiled.get("drive_writes") == 0
        and compiled.get("ai_calls") == 0
    )
    return {
        "schema": "IRONMAN_COACHING_RADAR_AI_CONTEXT_EVAL_V1",
        "pass": passed,
        "missing_categories": missing_categories,
        "missing_role_families": missing_roles,
        "category_routing_misses": category_routing_misses,
        "matched_terms": sorted(matched_terms),
        "selected_char_count": chars,
        "max_chars": max_chars,
        "duplicate_excerpts": duplicate_excerpts,
        "excerpt_count": len(excerpts),
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
    }
