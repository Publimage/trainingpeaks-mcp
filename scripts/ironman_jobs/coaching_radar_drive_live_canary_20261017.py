"""Live read-only Google Drive canary for IRONMAN canonical KB access.

Prints metadata only; document content and credentials are never printed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.ironman_jobs.coaching_radar_drive_context_adapter_v0 import (
    ContextDocumentSpec,
    DRIVE_READONLY_SCOPE,
    GoogleDriveContextReader,
    service_account_session,
)


def _validate_credentials_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError("KB_CREDENTIALS_FILE_MISSING")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise RuntimeError(f"KB_CREDENTIALS_FILE_PERMISSIONS_TOO_OPEN:{oct(mode)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials-file", required=True)
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--expected-title", required=True)
    args = parser.parse_args()

    credentials = Path(args.credentials_file)
    _validate_credentials_file(credentials)

    session = service_account_session(str(credentials))
    reader = GoogleDriveContextReader(session)
    entry, content = reader.read_document(
        ContextDocumentSpec(
            role="live_canary",
            document_id=args.document_id,
            expected_title=args.expected_title,
        )
    )
    print("RADAR_DRIVE_LIVE_CANARY_PASS")
    print(json.dumps({
        "title": entry["title"],
        "source": entry["source"],
        "source_version": entry["source_version"],
        "version_kind": entry["version_kind"],
        "content_sha256": entry["content_sha256"],
        "content_bytes": len(content.encode("utf-8")),
        "oauth_scope": DRIVE_READONLY_SCOPE,
        "drive_writes": 0,
        "trainingpeaks_writes": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
