"""Validate canonical Google Drive context bundles for the active Radar roster.

Live canary only. No AI call, no Google Drive write, no TrainingPeaks write.
Outputs fingerprints and counts, never document contents.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

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
        int(item["athlete_id"]): str(item["name"])
        for item in raw["athletes"]
        if item.get("enabled")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials-file", required=True)
    parser.add_argument("--sources-file", required=True)
    parser.add_argument("--athlete-id", action="append", type=int)
    args = parser.parse_args()

    roster = _roster()
    selected = sorted(set(args.athlete_id or roster))
    unknown = [value for value in selected if value not in roster]
    if unknown:
        raise ValueError(f"KB_CANARY_ATHLETE_NOT_ACTIVE:{unknown}")

    source_config = load_private_source_config(
        args.sources_file,
        active_athlete_ids=set(roster),
    )
    reader = CachedReader(
        GoogleDriveContextReader(service_account_session(args.credentials_file))
    )

    results = []
    for athlete_id in selected:
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
        validation = bundle["validation"]
        results.append({
            "athlete_id": athlete_id,
            "athlete_name": roster[athlete_id],
            "ai_context_gate": validation["ai_context_gate"],
            "document_count": validation["document_count"],
            "specialist_document_count": validation["specialist_document_count"],
            "context_fingerprint_sha256": validation["context_fingerprint_sha256"],
        })

    print("RADAR_DRIVE_CONTEXT_ROSTER_CANARY_PASS")
    print(json.dumps({
        "athlete_count": len(results),
        "results": results,
        "drive_writes": 0,
        "trainingpeaks_writes": 0,
        "ai_calls": 0,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
