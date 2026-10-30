"""Real loopback TLS, bounded admission and shutdown; no provider operations.

Disposable PKI uses stdlib SSL contexts so these transport tests also run on
Windows. Protected POSIX host-file loading remains covered by the peer suite.
"""

import datetime
import hashlib
import ipaddress
import socket
import ssl
import threading
import time
from contextlib import contextmanager, suppress
from http.client import HTTPSConnection
from http.server import BaseHTTPRequestHandler

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from tp_mcp.bridge_tls import BridgeHTTPServer, BridgeTLSError, authenticated_peer


@pytest.fixture
def pki(tmp_path):
    now = datetime.datetime.now(datetime.timezone.utc)

    def certificate(name, issuer=None, issuer_key=None):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        builder = (x509.CertificateBuilder().subject_name(subject)
                   .issuer_name(issuer.subject if issuer else subject)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - datetime.timedelta(minutes=1))
                   .not_valid_after(now + datetime.timedelta(hours=1))
                   .add_extension(x509.BasicConstraints(ca=issuer is None, path_length=None), True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
                       issuer.public_key() if issuer else key.public_key()), False))
        if issuer is None:
            builder = builder.add_extension(x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ), True)
        if name == "server":
            builder = builder.add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]), False)
        if issuer:
            usage = ExtendedKeyUsageOID.SERVER_AUTH if name == "server" else ExtendedKeyUsageOID.CLIENT_AUTH
            builder = builder.add_extension(x509.ExtendedKeyUsage([usage]), False)
        cert = builder.sign(issuer_key or key, hashes.SHA256())
        cert_path, key_path = tmp_path / f"{name}.pem", tmp_path / f"{name}.key"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                             serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        return cert, key, cert_path, key_path

    ca, ca_key, ca_path, _ = certificate("ca")
    _, _, server_cert, server_key = certificate("server", ca, ca_key)
    client, _, client_cert, client_key = certificate("client", ca, ca_key)
    _, _, other_cert, other_key = certificate("other", ca, ca_key)
    server = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH, cafile=str(ca_path))
    server.minimum_version = ssl.TLSVersion.TLSv1_2
    server.verify_mode = ssl.CERT_REQUIRED
    server.load_cert_chain(server_cert, server_key)

    def client_context(cert=None, key=None):
        context = ssl.create_default_context(cafile=str(ca_path))
        if cert is not None:
            context.load_cert_chain(cert, key)
        return context

    return server, client_context(client_cert, client_key), {
        "tls": {"peers": {hashlib.sha256(client.public_bytes(serialization.Encoding.DER)).hexdigest(): {
            "sources": ["127.0.0.1"], "result_writer": False,
        }}},
    }, client_context(other_cert, other_key), client_context()


@contextmanager
def listener(pki, **limits):
    context, client, config, _, _ = pki

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            try:
                authenticated_peer(self.connection, self.client_address[0], config)
            except BridgeTLSError:
                self.send_error(403)
                return
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = BridgeHTTPServer(("127.0.0.1", 0), Handler, context, **limits)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server, client
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def active(server):
    with server._connection_lock:
        return len(server._connections)


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition did not become true"
        time.sleep(0.01)


def health(server, context):
    connection = HTTPSConnection("127.0.0.1", server.server_port, context=context, timeout=1)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def test_silent_tcp_peer_does_not_block_authenticated_client(pki):
    with (listener(pki, handshake_timeout=10) as (server, client),
          socket.create_connection(server.server_address, timeout=1)):
        wait_for(lambda: active(server) == 1)
        assert health(server, client) == 200
        # The first peer is still present: success was not caused by its timeout.
        wait_for(lambda: active(server) == 1)


@pytest.mark.parametrize("partial", [False, True])
def test_handshake_deadline_closes_silent_or_partial_tls_and_releases_capacity(pki, partial):
    with listener(pki, handshake_timeout=0.2, max_connections=1) as (server, client):
        with socket.create_connection(server.server_address, timeout=1) as peer:
            if partial:
                peer.sendall(b"\x16\x03\x03\x00\x40")  # Incomplete TLS record.
            wait_for(lambda: active(server) == 1)
            wait_for(lambda: active(server) == 0)
            assert peer.recv(1) == b""
        assert health(server, client) == 200


def test_capacity_is_bounded_overflow_closes_and_slots_are_reusable(pki):
    with listener(pki, handshake_timeout=10, max_connections=2) as (server, client):
        peers = [socket.create_connection(server.server_address, timeout=1) for _ in range(2)]
        try:
            wait_for(lambda: active(server) == 2)
            for _ in range(12):
                with socket.create_connection(server.server_address, timeout=1) as overflow:
                    assert overflow.recv(1) == b""
                assert active(server) == 2
        finally:
            for peer in peers:
                peer.close()
        wait_for(lambda: active(server) == 0)
        assert health(server, client) == 200


def test_authenticated_http_idle_timeout_releases_capacity(pki):
    with listener(pki, request_timeout=0.2, max_connections=1) as (server, client):
        with (socket.create_connection(server.server_address, timeout=1) as raw,
              client.wrap_socket(raw, server_hostname="127.0.0.1") as peer):
            wait_for(lambda: active(server) == 1)
            wait_for(lambda: active(server) == 0)
            assert peer.recv(1) == b""
        assert health(server, client) == 200


def test_shutdown_interrupts_handshakes_and_http_idle_without_waiting_for_deadline(pki):
    with (listener(pki, handshake_timeout=30, request_timeout=30) as (server, client),
          socket.create_connection(server.server_address, timeout=1) as silent,
          socket.create_connection(server.server_address, timeout=1) as raw,
          client.wrap_socket(raw, server_hostname="127.0.0.1") as idle):
        wait_for(lambda: active(server) == 2)
        start = time.monotonic()
        server.shutdown()
        server.server_close()
        assert time.monotonic() - start < 2
        assert silent.recv(1) == b""
        assert idle.recv(1) == b""
        wait_for(lambda: active(server) == 0)


def test_failed_thread_start_closes_socket_and_releases_slot(pki, monkeypatch):
    with listener(pki, max_connections=1) as (server, client):
        # Invoke admission directly to avoid racing the listener's own thread.
        left, right = socket.socketpair()
        try:
            with monkeypatch.context() as patch:
                def fail_start(_):
                    raise RuntimeError("synthetic thread creation failure")
                patch.setattr(threading.Thread, "start", fail_start)
                with pytest.raises(RuntimeError, match="synthetic"):
                    server.process_request(left, ("127.0.0.1", 0))
            assert left.fileno() == -1
            assert active(server) == 0
            assert health(server, client) == 200
        finally:
            left.close()
            right.close()


def test_tls_failures_and_pin_denial_do_not_leak_capacity(pki):
    with listener(pki, max_connections=1) as (server, client):
        with pytest.raises((OSError, EOFError)):
            health(server, pki[4])
        wait_for(lambda: active(server) == 0)
        assert health(server, pki[3]) == 403
        wait_for(lambda: active(server) == 0)
        assert health(server, client) == 200


def test_server_rejects_non_mtls_context():
    with pytest.raises(BridgeTLSError, match="MTLS_REQUIRED"):
        BridgeHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler, ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER))


def test_plaintext_is_not_a_fallback_and_does_not_leak_capacity(pki):
    with listener(pki, max_connections=1) as (server, client):
        with socket.create_connection(server.server_address, timeout=1) as peer:
            peer.sendall(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
            with suppress(ConnectionResetError):
                assert peer.recv(1024) == b""
        wait_for(lambda: active(server) == 0)
        assert health(server, client) == 200


def test_shutdown_before_worker_wraps_socket_releases_slot(pki, monkeypatch):
    with listener(pki) as (server, _):
        entered, resume = threading.Event(), threading.Event()
        original = server.process_request_thread

        def delayed(request, address):
            entered.set()
            assert resume.wait(2)
            original(request, address)

        monkeypatch.setattr(server, "process_request_thread", delayed)
        with socket.create_connection(server.server_address, timeout=1) as peer:
            try:
                assert entered.wait(1)
                server.shutdown()
                server.server_close()
                assert peer.recv(1) == b""
            finally:
                resume.set()
            wait_for(lambda: active(server) == 0)


def test_shutdown_bounds_idle_worker_even_if_client_does_not_read_eof(pki):
    with (listener(pki, request_timeout=0.2) as (server, client),
          socket.create_connection(server.server_address, timeout=1) as raw,
          client.wrap_socket(raw, server_hostname="127.0.0.1") as peer):
        wait_for(lambda: active(server) == 1)
        server.shutdown()
        server.server_close()
        # No recv/close on the client until the server worker has exited.
        wait_for(lambda: active(server) == 0)
        assert peer.recv(1) == b""
