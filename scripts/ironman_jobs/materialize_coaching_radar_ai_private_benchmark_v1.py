"""Materialize a private, reproducible 10-case Radar AI benchmark pack.

Reads:
- frozen Radar reports already on Prefect staging
- canonical Google Drive context through the read-only service account
- public-safe benchmark expectations from the repository

Writes only to a caller-specified local private output directory. No Drive,
TrainingPeaks or AI provider writes/calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from scripts.ironman_jobs.coaching_radar_ai_context_contract_v0 import build_ai_context_input
from scripts.ironman_jobs.coaching_radar_ai_context_compiler_v0 import (
    compile_selective_context,
    evaluate_compiled_context,
)
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


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_private_json(path: Path, value) -> str:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    return _sha_bytes(payload)


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
    parser.add_argument("--eval-cases-file", required=True)
    parser.add_argument("--benchmark-file", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--radar-dir", default=str(DEFAULT_RADAR_DIR))
    parser.add_argument("--max-total-chars", type=int, default=18000)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if output_dir.exists():
        raise RuntimeError("AI_BENCH_OUTPUT_DIR_ALREADY_EXISTS")
    output_dir.mkdir(parents=True, mode=0o700)
    os.chmod(output_dir, 0o700)

    roster = _roster()
    eval_raw = json.loads(Path(args.eval_cases_file).read_text(encoding="utf-8"))
    benchmark = json.loads(Path(args.benchmark_file).read_text(encoding="utf-8"))
    if eval_raw.get("as_of") != args.as_of or benchmark.get("as_of") != args.as_of:
        raise RuntimeError("AI_BENCH_AS_OF_MISMATCH")

    eval_cases = {int(x["athlete_id"]): x for x in eval_raw["cases"]}
    benchmark_cases = {int(x["athlete_id"]): x for x in benchmark["cases"]}
    if set(eval_cases) != set(roster) or set(benchmark_cases) != set(roster):
        raise RuntimeError("AI_BENCH_ROSTER_MISMATCH")

    source_config = load_private_source_config(
        args.sources_file,
        active_athlete_ids=set(roster),
    )
    reader = CachedReader(
        GoogleDriveContextReader(service_account_session(args.credentials_file))
    )

    manifest_cases = []
    for athlete_id in sorted(roster):
        eval_case = eval_cases[athlete_id]
        benchmark_case = benchmark_cases[athlete_id]

        report_path = Path(args.radar_dir) / str(athlete_id) / f"report_{args.as_of}.json"
        if not report_path.is_file():
            raise RuntimeError(f"AI_BENCH_REPORT_MISSING:{athlete_id}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("evidence_sha256") != eval_case["radar_evidence_sha256"]:
            raise RuntimeError(f"AI_BENCH_EVIDENCE_MISMATCH:{athlete_id}")
        if report.get("status") != eval_case["radar_status"]:
            raise RuntimeError(f"AI_BENCH_STATUS_MISMATCH:{athlete_id}")

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
        evaluation = evaluate_compiled_context(
            compiled,
            expected_categories=sorted(eval_case.get("categories") or []),
            expected_role_families=list(eval_raw.get("expected_role_families") or []),
            max_chars=args.max_total_chars,
            expected_data_quality_flags=list(eval_case.get("data_quality") or []),
        )
        if not evaluation["pass"]:
            raise RuntimeError(
                f"AI_BENCH_CONTEXT_EVAL_FAILED:{athlete_id}:"
                + json.dumps(evaluation, sort_keys=True)
            )

        private_case = {
            "schema": "IRONMAN_RADAR_AI_PRIVATE_BENCHMARK_CASE_V1",
            "athlete_id": athlete_id,
            "athlete_name": roster[athlete_id],
            "as_of": args.as_of,
            "radar": packet["radar"],
            "selective_context": {
                "schema": compiled["schema"],
                "context_fingerprint_sha256": compiled["context_fingerprint_sha256"],
                "compiled_fingerprint_sha256": compiled["compiled_fingerprint_sha256"],
                "selected_char_count": compiled["selected_char_count"],
                "signal_categories": compiled["signal_categories"],
                "excerpts": compiled["excerpts"],
            },
            "guardrails": packet["guardrails"],
            "benchmark_expectations": benchmark_case,
            "input_fingerprint_sha256": packet["input_fingerprint_sha256"],
            "trainingpeaks_writes": 0,
            "drive_writes": 0,
            "ai_calls": 0,
        }

        filename = f"case_{athlete_id}.json"
        file_sha = _write_private_json(output_dir / filename, private_case)
        manifest_cases.append({
            "athlete_id": athlete_id,
            "filename": filename,
            "file_sha256": file_sha,
            "radar_evidence_sha256": report["evidence_sha256"],
            "context_fingerprint_sha256": compiled["context_fingerprint_sha256"],
            "compiled_fingerprint_sha256": compiled["compiled_fingerprint_sha256"],
            "selected_char_count": compiled["selected_char_count"],
            "evaluation_gate": "PASS",
        })

    manifest = {
        "schema": "IRONMAN_RADAR_AI_PRIVATE_BENCHMARK_MANIFEST_V1",
        "as_of": args.as_of,
        "case_count": len(manifest_cases),
        "cases": manifest_cases,
        "private_payload_location": str(output_dir),
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
        "gate": "PASS",
    }
    manifest_sha = _write_private_json(output_dir / "manifest.json", manifest)

    print("RADAR_AI_PRIVATE_BENCHMARK_MATERIALIZE_PASS")
    print(json.dumps({
        "case_count": len(manifest_cases),
        "manifest_sha256": manifest_sha,
        "output_dir": str(output_dir),
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
