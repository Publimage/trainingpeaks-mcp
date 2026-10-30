"""Standard mutual TLS for the existing private bridge, with pinned peer roles.

No issuer, key, certificate or service is created. Protected host configuration
supplies existing PKI material. IP allowlists remain an additional network gate.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import socket
import ssl
import threading
from contextlib import suppress
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, build_opener


class BridgeTLSError(PermissionError):
    pass


class BridgeHTTPServer(ThreadingHTTPServer):
    """Bounded per-connection TLS on the existing HTTP server.

    The listener stays TCP, but no request reaches an HTTP handler before mTLS.
    Admission never waits for a slot. All connections, including keep-alives,
    occupy a slot until closed. This bounds resources, not hostile-network load.
    """

    def __init__(self, address, handler, context: ssl.SSLContext, *,
                 handshake_timeout: float = 5, request_timeout: float = 30,
                 max_connections: int = 32):
        if context.verify_mode != ssl.CERT_REQUIRED:
            raise BridgeTLSError("BRIDGE_MTLS_REQUIRED")
        if (type(max_connections) is not int or max_connections < 1
                or any(type(t) not in (int, float) or not math.isfinite(t) or t <= 0
                       for t in (handshake_timeout, request_timeout))):
            raise ValueError("BRIDGE_CONNECTION_LIMITS_INVALID")
        self._tls_context = context
        self._handshake_timeout = handshake_timeout
        self._request_timeout = request_timeout
        self._slots = threading.BoundedSemaphore(max_connections)
        self._connections: set[socket.socket] = set()
        self._connection_lock = threading.Lock()
        self._closing = False
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            with self._connection_lock:
                if self._closing:
                    self.shutdown_request(request)
                    self._slots.release()
                    return
                self._connections.add(request)
            super().process_request(request, client_address)
        except Exception:
            self.shutdown_request(request)
            with self._connection_lock:
                self._slots.release()
                self._connections.discard(request)
            raise

    def process_request_thread(self, request, client_address):
        connection = request
        try:
            # Serialize only the ownership transfer with server_close(). No
            # network I/O or handshake takes place while this lock is held.
            with self._connection_lock:
                if self._closing:
                    return
                connection = self._tls_context.wrap_socket(
                    request, server_side=True, do_handshake_on_connect=False,
                )
                self._connections.discard(request)
                self._connections.add(connection)
            connection.settimeout(self._handshake_timeout)
            connection.do_handshake()
            with self._connection_lock:
                if self._closing:
                    return
            connection.settimeout(self._request_timeout)
            self.finish_request(connection, client_address)
        except (OSError, ValueError):
            # Invalid/absent client certificates, handshake deadlines and
            # sockets interrupted by shutdown all close without an HTTP reply.
            pass
        except Exception:
            self.handle_error(connection, client_address)
        finally:
            try:
                self.shutdown_request(connection)
            finally:
                with self._connection_lock:
                    self._slots.release()
                    self._connections.discard(connection)
                    self._connections.discard(request)

    def server_close(self):
        with self._connection_lock:
            self._closing = True
            connections = tuple(self._connections)
        super().server_close()
        # Signal TCP closure without waiting for the peer. Pending reads still
        # have finite deadlines; provider work is not cancelled by socket IO.
        for connection in connections:
            with suppress(OSError):
                # Do not clear SSLSocket._sslobj while another thread is using
                # it. Interrupt TCP IO; the owning worker closes its TLS socket.
                socket.socket.shutdown(connection, socket.SHUT_RDWR)
            connection.close()


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
