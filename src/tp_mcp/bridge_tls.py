"""Standard mutual TLS for the existing private bridge, with pinned peer roles.

No issuer, key, certificate or service is created. Protected host configuration
supplies existing PKI material. IP allowlists remain an additional network gate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
from pathlib import Path
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, build_opener


class BridgeTLSError(PermissionError):
    pass


def validate_tls_config(value: object, *, server: bool = False) -> dict:
    fields = {"ca_file", "cert_file", "key_file"} | ({"peers"} if server else set())
    if type(value) is not dict or set(value) != fields:
        raise BridgeTLSError("BRIDGE_MTLS_CONFIGURATION_REQUIRED")
    for key in ("ca_file", "cert_file", "key_file"):
        if type(value[key]) is not str or not Path(value[key]).is_absolute():
            raise BridgeTLSError("BRIDGE_MTLS_HOST_PATH_REQUIRED")
    if server:
        peers = value["peers"]
        if type(peers) is not dict or not peers:
            raise BridgeTLSError("BRIDGE_MTLS_PEERS_REQUIRED")
        for fingerprint, rule in peers.items():
            if (type(fingerprint) is not str or re.fullmatch(r"[a-f0-9]{64}", fingerprint) is None
                    or type(rule) is not dict or set(rule) != {"sources", "result_writer"}
                    or type(rule["sources"]) is not list or not rule["sources"]
                    or not all(type(ip) is str for ip in rule["sources"])
                    or type(rule["result_writer"]) is not bool):
                raise BridgeTLSError("BRIDGE_MTLS_PEER_POLICY_INVALID")
    return value


def tls_context(config: dict, *, server: bool = False) -> ssl.SSLContext:
    from scripts.ironman_jobs.ironman_authorization import read_host_file

    config = validate_tls_config(config, server=server)
    # Reuse the existing private-host path/owner/symlink reader, never repair it.
    for field in ("ca_file", "cert_file", "key_file"):
        read_host_file(Path(config[field]), 1_048_576)
    purpose = ssl.Purpose.CLIENT_AUTH if server else ssl.Purpose.SERVER_AUTH
    context = ssl.create_default_context(purpose, cafile=config["ca_file"])
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(config["cert_file"], config["key_file"])
    return context


def authenticated_peer(connection: object, source: str, config: dict) -> dict:
    if not isinstance(connection, ssl.SSLSocket) or connection.context.verify_mode != ssl.CERT_REQUIRED:
        raise BridgeTLSError("BRIDGE_AUTHENTICATED_PEER_REQUIRED")
    certificate = connection.getpeercert(binary_form=True)
    rule = config.get("tls", {}).get("peers", {}).get(hashlib.sha256(certificate or b"").hexdigest())
    if not rule or source not in rule["sources"]:
        raise BridgeTLSError("BRIDGE_PEER_NOT_AUTHORIZED")
    return rule


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def bridge_client_opener():
    from scripts.ironman_jobs.ironman_authorization import read_host_file

    path = os.environ.get("IRONMAN_PRIVATE_BRIDGE_TLS_CONFIG")
    if not path:
        raise BridgeTLSError("BRIDGE_MTLS_CLIENT_REQUIRED")
    config = json.loads(read_host_file(Path(path), 65536))
    return build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=tls_context(config)))
