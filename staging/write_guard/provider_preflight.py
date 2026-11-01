"""Read-only staging identity and Google Docs reachability check.

Prints neither tokens nor full document contents. Requires a trusted on-host
configuration and service-account ADC; cannot be invoked by a chat payload.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

from authenticated_bridge import make_service_account_connector
from google_docs_adapter import GoogleDocsConnectorAdapter
from inbound_api import load_trusted_config


def check_readiness(config_path: str, *, connector_factory=make_service_account_connector):
    cfg = load_trusted_config(config_path)
    try:
        connector = connector_factory(expected_email=cfg.service_account_email)
    except Exception as exc:
        return {"state": "GOOGLE_IDENTITY_UNAVAILABLE", "reason_class": type(exc).__name__}
    summaries = []
    try:
        adapter = GoogleDocsConnectorAdapter(connector)
        for doc_id in sorted(cfg.allowed_documents):
            doc = adapter.read(doc_id)
            summaries.append({
                "document_suffix": doc_id[-5:],
                "revision_digest": hashlib.sha256(doc.revision.encode()).hexdigest()[:12],
            })
    except Exception as exc:
        return {"state": "GOOGLE_DOCUMENT_UNAVAILABLE", "reason_class": type(exc).__name__,
                "documents_verified": len(summaries)}
    return {"state": "READONLY_PROVIDER_ACCESS_VERIFIED", "documents_verified": len(summaries),
            "documents": summaries, "write_tested": False}


def main() -> int:
    path = os.environ.get("WG_CONFIG_PATH")
    if not path:
        print(json.dumps({"state": "CONFIGURATION_MISSING"}))
        return 2
    try:
        report = check_readiness(path)
    except Exception as exc:
        report = {"state": "INVALID_TRUSTED_CONFIGURATION", "reason_class": type(exc).__name__}
    print(json.dumps(report, separators=(",", ":")))
    return 0 if report["state"] == "READONLY_PROVIDER_ACCESS_VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
