"""Privacy-minimized external-provider payload for Radar AI benchmark.

Transforms a private benchmark case into a provider-facing payload without
athlete name, TrainingPeaks athlete ID, Google Drive document IDs, server paths,
or source titles that can carry athlete identity. No network/provider calls.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "IRONMAN_RADAR_AI_PROVIDER_PAYLOAD_V1"

_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d .()/-]{7,}\d)(?!\d)")
_URL_RE = re.compile(r"(?i)https?://[^\s)\]}>]+")


def _replace_literal(text: str, value: str, replacement: str) -> str:
    if not value:
        return text
    return re.sub(re.escape(value), replacement, text, flags=re.IGNORECASE)


def _redact_text(
    text: str,
    *,
    athlete_name: str,
    athlete_id: int,
    additional_names: tuple[str, ...] = (),
    additional_ids: tuple[int, ...] = (),
) -> str:
    out = text
    all_names = tuple(dict.fromkeys((athlete_name, *additional_names)))
    all_ids = tuple(dict.fromkeys((athlete_id, *additional_ids)))
    for name in all_names:
        out = _replace_literal(out, name, "<ATHLETE>")
    name_tokens = {
        part.strip(".,;:()[]{}")
        for name in all_names
        for part in name.split()
    }
    for token in sorted(
        name_tokens,
        key=len,
        reverse=True,
    ):
        if len(token) >= 3:
            out = re.sub(
                rf"(?i)(?<![A-ZÀ-ÖØ-öø-ÿ]){re.escape(token)}(?![A-ZÀ-ÖØ-öø-ÿ])",
                "<ATHLETE_NAME_PART>",
                out,
            )
    for private_id in all_ids:
        out = re.sub(rf"(?<!\d){re.escape(str(private_id))}(?!\d)", "<ATHLETE_ID>", out)
    out = _EMAIL_RE.sub("<EMAIL>", out)
    out = _PHONE_RE.sub("<PHONE>", out)
    out = _URL_RE.sub("<URL>", out)
    return out


def _role_label(role: str) -> str:
    if role.startswith("specialist:"):
        return "specialist"
    return role


def _sanitize_data_quality(
    value: dict[str, Any],
    *,
    athlete_name: str,
    athlete_id: int,
    additional_names: tuple[str, ...] = (),
    additional_ids: tuple[int, ...] = (),
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, item in value.items():
        lower = key.lower()
        if lower in {"athlete_id", "workout_id", "user_id", "id"} or lower.endswith("_id"):
            continue
        if lower.endswith("_ids") and isinstance(item, list):
            out[key[:-4] + "_count"] = len(item)
            continue
        if isinstance(item, str):
            out[key] = _redact_text(
                item,
                athlete_name=athlete_name,
                athlete_id=athlete_id,
                additional_names=additional_names,
                additional_ids=additional_ids,
            )
        elif isinstance(item, dict):
            out[key] = _sanitize_data_quality(
                item,
                athlete_name=athlete_name,
                athlete_id=athlete_id,
                additional_names=additional_names,
                additional_ids=additional_ids,
            )
        elif isinstance(item, list):
            sanitized = []
            for sub in item:
                if isinstance(sub, str):
                    sanitized.append(_redact_text(sub, athlete_name=athlete_name, athlete_id=athlete_id, additional_names=additional_names, additional_ids=additional_ids))
                elif isinstance(sub, dict):
                    sanitized.append(_sanitize_data_quality(
                        sub,
                        athlete_name=athlete_name,
                        athlete_id=athlete_id,
                        additional_names=additional_names,
                        additional_ids=additional_ids,
                    ))
                else:
                    sanitized.append(sub)
            out[key] = sanitized
        else:
            out[key] = item
    return out


def build_provider_payload(
    private_case: dict[str, Any],
    *,
    output_schema: dict[str, Any],
    behavior_taxonomy: dict[str, Any],
    additional_private_bindings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if private_case.get("schema") != "IRONMAN_RADAR_AI_PRIVATE_BENCHMARK_CASE_V1":
        raise ValueError("PROVIDER_PAYLOAD_PRIVATE_CASE_SCHEMA_MISMATCH")
    athlete_id = int(private_case.get("athlete_id") or 0)
    athlete_name = str(private_case.get("athlete_name") or "")
    if athlete_id <= 0 or not athlete_name:
        raise ValueError("PROVIDER_PAYLOAD_ATHLETE_BINDING_MISSING")
    additional_private_bindings = additional_private_bindings or []
    additional_names = tuple(
        str(x.get("athlete_name") or "")
        for x in additional_private_bindings
        if str(x.get("athlete_name") or "") and str(x.get("athlete_name") or "") != athlete_name
    )
    additional_ids = tuple(
        int(x.get("athlete_id") or 0)
        for x in additional_private_bindings
        if int(x.get("athlete_id") or 0) > 0 and int(x.get("athlete_id") or 0) != athlete_id
    )

    radar = private_case.get("radar")
    selective = private_case.get("selective_context")
    if not isinstance(radar, dict) or not isinstance(selective, dict):
        raise ValueError("PROVIDER_PAYLOAD_CASE_INCOMPLETE")
    if behavior_taxonomy.get("schema") != "IRONMAN_RADAR_AI_BEHAVIOR_TAXONOMY_V1":
        raise ValueError("PROVIDER_PAYLOAD_TAXONOMY_SCHEMA_MISMATCH")

    evidence_sha = str(radar.get("evidence_sha256") or "")
    if len(evidence_sha) != 64:
        raise ValueError("PROVIDER_PAYLOAD_EVIDENCE_SHA_INVALID")
    case_ref = "radar-" + hashlib.sha256(
        f"{evidence_sha}:{private_case.get('as_of')}".encode("utf-8")
    ).hexdigest()[:16]

    redacted_alerts = json.loads(json.dumps(radar.get("alerts") or []))
    redacted_upcoming = json.loads(json.dumps(radar.get("upcoming") or []))
    for collection in (redacted_alerts, redacted_upcoming):
        for item in collection:
            if not isinstance(item, dict):
                continue
            item.pop("workout_id", None)
            item.pop("athlete_id", None)
            for key, value in list(item.items()):
                if isinstance(value, str):
                    item[key] = _redact_text(value, athlete_name=athlete_name, athlete_id=athlete_id, additional_names=additional_names, additional_ids=additional_ids)

    excerpts = []
    for item in selective.get("excerpts") or []:
        role = str(item.get("role") or "")
        excerpt = _redact_text(
            str(item.get("excerpt") or ""),
            athlete_name=athlete_name,
            athlete_id=athlete_id,
        )
        excerpts.append({
            "source_role": _role_label(role),
            "section_heading": _redact_text(
                str(item.get("section_heading") or ""),
                athlete_name=athlete_name,
                athlete_id=athlete_id,
                additional_names=additional_names,
                additional_ids=additional_ids,
            ),
            "matched_terms": list(item.get("matched_terms") or []),
            "excerpt": excerpt,
            "source_excerpt_sha256": item.get("excerpt_sha256"),
            "provider_excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        })

    payload = {
        "schema": SCHEMA,
        "mode": "SHADOW_READ_ONLY",
        "case_ref": case_ref,
        "as_of": private_case["as_of"],
        "radar": {
            "status": radar.get("status"),
            "review_required": bool(radar.get("review_required")),
            "alerts": redacted_alerts,
            "upcoming": redacted_upcoming,
            "data_quality": _sanitize_data_quality(
                radar.get("data_quality") or {},
                athlete_name=athlete_name,
                athlete_id=athlete_id,
            ),
            "evidence_sha256": evidence_sha,
        },
        "context": {
            "context_fingerprint_sha256": selective.get("context_fingerprint_sha256"),
            "compiled_fingerprint_sha256": selective.get("compiled_fingerprint_sha256"),
            "excerpts": excerpts,
        },
        "output_contract": {
            "output_schema": output_schema,
            "behavior_taxonomy": behavior_taxonomy,
        },
        "instructions": {
            "purpose": "analysis_for_coach_review_only",
            "coach_is_final_decision_maker": True,
            "cite_evidence_refs": True,
            "state_uncertainty": True,
            "do_not_infer_missing_data_as_positive_evidence": True,
            "no_external_tools": True,
            "no_web_search": True,
            "no_provider_file_uploads": True,
            "trainingpeaks_writes_allowed": False,
            "drive_writes_allowed": False,
            "workout_mutations_allowed": False,
        },
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    forbidden_literals = [
        *(name.lower() for name in (athlete_name, *additional_names)),
        *(str(value) for value in (athlete_id, *additional_ids)),
        "/var/lib/ironman-prefect",
    ]
    lower = serialized.lower()
    leaked = [x for x in forbidden_literals if x and x in lower]

    forbidden_keys = {"athlete_id", "athlete_name", "document_id", "workout_id", "user_id"}
    leaked_keys: set[str] = set()

    def inspect_keys(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in forbidden_keys:
                    leaked_keys.add(str(key).lower())
                inspect_keys(item)
        elif isinstance(value, list):
            for item in value:
                inspect_keys(item)

    inspect_keys(payload)
    if leaked or leaked_keys:
        details = leaked + sorted(leaked_keys)
        raise ValueError("PROVIDER_PAYLOAD_IDENTIFIER_LEAK:" + ",".join(details))

    payload["provider_payload_sha256"] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return payload
