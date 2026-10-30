"""Actual mTLS peer boundary; all certificates and provider data are disposable."""

import json
import ssl
import threading
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPSConnection
from http.server import ThreadingHTTPServer

import pytest
from bridge_tls_fixture import bridge_tls_material

from tp_mcp.bridge_tls import BridgeHTTPServer
from tp_mcp.private_bridge import _handler_factory


@contextmanager
def listener(config, tmp_path, *, secure=True):
    tls = bridge_tls_material(config, tmp_path) if secure else None
    if secure:
        server = BridgeHTTPServer(("127.0.0.1", 0), _handler_factory(config), tls.server_context)
        tls.connection = lambda: HTTPSConnection("127.0.0.1", server.server_port, context=tls.context, timeout=5)
    else:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_factory(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, tls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def config():
    return {
        "allowed_sources": {"127.0.0.1"},
        "result_writer_sources": {"127.0.0.1"},
        "allowed_athletes": {"123"},
        "max_window_days": 21,
        "allowed_unified_reads": [],
    }


def test_allowlisted_ip_and_spoofed_headers_are_not_peer_authentication(tmp_path):
    with listener(config(), tmp_path, secure=False) as (server, _):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("GET", "/health", headers={"X-Forwarded-For": "10.114.0.3", "X-Client-Cert": "fake"})
        response = connection.getresponse()
        assert response.status == 403
        assert json.loads(response.read())["error"] == "BRIDGE_PEER_NOT_AUTHORIZED"
        connection.close()


@pytest.mark.parametrize("identity", ["anonymous", "untrusted", "wrong_source", "reader"])
def test_tls_certificate_role_and_network_binding_gate_before_receipt_write(tmp_path, monkeypatch, identity):
    import tp_mcp.private_bridge as bridge

    persisted = []
    monkeypatch.setattr(bridge, "_persist_admin_result", lambda *_: persisted.append(True))
    cfg = config()
    with listener(cfg, tmp_path) as (server, tls):
        context = tls.anonymous if identity == "anonymous" else tls.other if identity == "untrusted" else tls.context
        if identity == "wrong_source":
            next(iter(cfg["tls"]["peers"].values()))["sources"] = ["10.0.0.9"]
        connection = HTTPSConnection("127.0.0.1", server.server_port, context=context, timeout=5)
        try:
            if identity == "anonymous":
                with pytest.raises((ssl.SSLError, OSError)):
                    connection.request("POST", "/v1/admin-result", body="{}")
                    connection.getresponse()
            else:
                connection.request("POST", "/v1/admin-result", body="{}")
                response = connection.getresponse()
                assert response.status == 403
                response.read()
        finally:
            connection.close()
    assert persisted == []


def test_pinned_mtls_peer_is_accepted_and_still_needs_result_writer_role(tmp_path, monkeypatch):
    import tp_mcp.private_bridge as bridge

    persisted = []
    monkeypatch.setattr(bridge, "_persist_admin_result", lambda *_: persisted.append(True) or {"stored": True})
    cfg = config()
    with listener(cfg, tmp_path) as (server, tls):
        next(iter(cfg["tls"]["peers"].values()))["result_writer"] = True
        connection = tls.connection()
        connection.request("GET", "/health")
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        connection.request("POST", "/v1/admin-result", body="{}")
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        connection.close()
    assert persisted == [True]


def test_universal_client_missing_tls_configuration_is_security_denial(monkeypatch):
    from test_ironman_unified_private_bridge import spec

    from scripts.ironman_jobs.ironman_unified_changeset_engine import SecurityDenied
    from tp_mcp.unified_read_bridge import PrivateBridgeReadAdapter

    monkeypatch.delenv("IRONMAN_PRIVATE_BRIDGE_TLS_CONFIG", raising=False)
    with pytest.raises(SecurityDenied, match="MTLS_REQUIRED"):
        PrivateBridgeReadAdapter().read(spec())


@pytest.mark.parametrize("failure", ["ca", "hostname"])
def test_client_verifies_bridge_server_identity(tmp_path, failure):
    with listener(config(), tmp_path) as (server, tls):
        context = ssl.create_default_context() if failure == "ca" else tls.context
        host = "127.0.0.1" if failure == "ca" else "localhost"
        connection = HTTPSConnection(host, server.server_port, context=context, timeout=5)
        try:
            with pytest.raises(ssl.SSLCertVerificationError):
                connection.request("GET", "/health")
        finally:
            connection.close()


def test_configured_bridge_cannot_start_from_legacy_ip_only_configuration(tmp_path):
    from tp_mcp.private_bridge import BridgeConfigError, _load_config

    path = tmp_path / "bridge.json"
    path.write_text(
        json.dumps(
            {
                "host": "10.114.0.2",
                "port": 8787,
                "allowed_sources": ["10.114.0.3"],
                "result_writer_sources": ["10.114.0.3"],
                "allowed_athletes": ["123"],
                "max_window_days": 21,
            }
        )
    )
    path.chmod(0o600)
    with pytest.raises(BridgeConfigError, match="MTLS_CONFIGURATION_REQUIRED"):
        _load_config(path)
