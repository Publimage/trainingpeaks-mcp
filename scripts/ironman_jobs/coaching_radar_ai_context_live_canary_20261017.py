"""Live, read-only canary for the Radar AI selective context compiler.

Uses existing local Radar reports and the already authorized Google Drive
read-only service account. No AI provider call and no writes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.ironman_jobs.coaching_radar_ai_context_contract_v0 import build_ai_context_input
from scripts.ironman_jobs.coaching_radar_ai_context_compiler_v0 import compile_selective_context
from scripts.ironman_jobs.coaching_radar_context_sources_v0 import (
    context_specs_for_athlete,
    load_private_source_config,
)
from scripts.ironman_jobs.coaching_radar_drive_context_adapter_v0 import (
    GoogleDriveContextReader,
    build_context_bundle,
    service_account_session,
)

ROSTER = Path("/opt/ironman-prefect/radar-src/data/coaching_radar_alberto_group_v1.json")
DEFAULT_RADAR_DIR = Path("/var/lib/ironman-prefect/radar")


class CachedReader:
    def __init__(self, reader):
        self.reader = reader
        self.cache = {}

    def read_document(self, spec):
        key = (spec.document_id, spec.expected_title)
        if key not in self.cache:
            self.cache[key] = self.reader.read_document(spec)
        return self.cache[key]


def _roster() -> dict[int, str]:
    raw = json.loads(ROSTER.read_text(encoding="utf-8"))
    return {
        int(x["athlete_id"]): str(x["name"])
        for x in raw["athletes"]
        if x.get("enabled")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials-file", required=True)
    parser.add_argument("--sources-file", required=True)
    parser.add_argument("--radar-dir", default=str(DEFAULT_RADAR_DIR))
    parser.add_argument("--max-total-chars", type=int, default=18000)
    args = parser.parse_args()

    roster = _roster()
    source_config = load_private_source_config(
        args.sources_file,
        active_athlete_ids=set(roster),
    )
    reader = CachedReader(
        GoogleDriveContextReader(service_account_session(args.credentials_file))
    )

    results = []
    for athlete_id in sorted(roster):
        report_path = Path(args.radar_dir) / str(athlete_id) / "latest.json"
        if not report_path.is_file():
            raise RuntimeError(f"AI_CONTEXT_RADAR_REPORT_MISSING:{athlete_id}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if int(report.get("athlete_id") or 0) != athlete_id:
            raise RuntimeError(f"AI_CONTEXT_RADAR_REPORT_ATHLETE_MISMATCH:{athlete_id}")

        documents, specialist = context_specs_for_athlete(
            source_config,
            athlete_id=athlete_id,
        )
        bundle = build_context_bundle(
            reader,
            athlete_id=athlete_id,
            documents=documents,
            specialist_documents=specialist,
        )
        packet = build_ai_context_input(report, bundle)
        compiled = compile_selective_context(
            packet,
            max_total_chars=args.max_total_chars,
        )
        results.append({
            "athlete_id": athlete_id,
            "athlete_name": roster[athlete_id],
            "signal_categories": compiled["signal_categories"],
            "excerpt_count": compiled["excerpt_count"],
            "selected_char_count": compiled["selected_char_count"],
            "input_fingerprint_sha256": compiled["input_fingerprint_sha256"],
            "context_fingerprint_sha256": compiled["context_fingerprint_sha256"],
            "compiled_fingerprint_sha256": compiled["compiled_fingerprint_sha256"],
        })

    print("RADAR_AI_SELECTIVE_CONTEXT_LIVE_CANARY_PASS")
    print(json.dumps({
        "athlete_count": len(results),
        "max_total_chars": args.max_total_chars,
        "results": results,
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
