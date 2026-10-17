"""Materialize privacy-minimized provider payloads from private Radar AI benchmark.

No network calls. Reads the private benchmark pack and writes a separate 0700
directory of 0600 provider-facing JSON payloads plus a size/cost-planning
summary. Direct identifiers remain only in the private benchmark source pack.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from scripts.ironman_jobs.coaching_radar_ai_provider_payload_v1 import build_provider_payload


def _write_private(path: Path, value) -> int:
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
    return len(payload)


def materialize(private_dir: Path, output_dir: Path, schema_file: Path) -> dict:
    if output_dir.exists():
        raise RuntimeError("PROVIDER_PAYLOAD_OUTPUT_DIR_ALREADY_EXISTS")
    manifest_path = private_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("PRIVATE_BENCHMARK_MANIFEST_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("gate") != "PASS" or int(manifest.get("case_count") or 0) != 10:
        raise RuntimeError("PRIVATE_BENCHMARK_GATE_NOT_PASS")

    output_schema = json.loads(schema_file.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, mode=0o700)
    os.chmod(output_dir, 0o700)

    rows = []
    total_chars = 0
    total_bytes = 0
    for item in manifest["cases"]:
        src = private_dir / item["filename"]
        case = json.loads(src.read_text(encoding="utf-8"))
        payload = build_provider_payload(case, output_schema=output_schema)
        filename = f"provider_{payload['case_ref']}.json"
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        char_count = len(text)
        byte_count = _write_private(output_dir / filename, payload)
        total_chars += char_count
        total_bytes += byte_count
        rows.append({
            "case_ref": payload["case_ref"],
            "filename": filename,
            "provider_payload_sha256": payload["provider_payload_sha256"],
            "char_count": char_count,
            "byte_count": byte_count,
            "approx_input_tokens_typical_chars4": math.ceil(char_count / 4),
            "approx_input_tokens_conservative_chars3": math.ceil(char_count / 3),
        })

    summary = {
        "schema": "IRONMAN_RADAR_AI_PROVIDER_PAYLOAD_SUMMARY_V1",
        "case_count": len(rows),
        "cases": rows,
        "total_chars": total_chars,
        "total_bytes": total_bytes,
        "approx_input_tokens_typical_chars4": math.ceil(total_chars / 4),
        "approx_input_tokens_conservative_chars3": math.ceil(total_chars / 3),
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
        "gate": "PASS",
    }
    _write_private(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-benchmark-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--review-schema-file", required=True)
    args = parser.parse_args()
    result = materialize(
        Path(args.private_benchmark_dir),
        Path(args.output_dir),
        Path(args.review_schema_file),
    )
    print("RADAR_AI_PROVIDER_PAYLOAD_MATERIALIZE_PASS")
    print(json.dumps({
        "case_count": result["case_count"],
        "total_chars": result["total_chars"],
        "total_bytes": result["total_bytes"],
        "approx_input_tokens_typical_chars4": result["approx_input_tokens_typical_chars4"],
        "approx_input_tokens_conservative_chars3": result["approx_input_tokens_conservative_chars3"],
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
