"""Shared disposable PKI material for private-bridge tests only."""

import datetime
import hashlib
import ipaddress
import json
import ssl
from http.client import HTTPSConnection
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from tp_mcp.bridge_tls import tls_context


def tls_metadata():
    return {
        "ca_file": "/synthetic/ca.pem",
        "cert_file": "/synthetic/server.pem",
        "key_file": "/synthetic/key.pem",
        "peers": {"0" * 64: {"sources": ["127.0.0.1"], "result_writer": False}},
    }


def secure_bridge_server(server, config, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)

    def write(name, data):
        path = directory / name
        path.write_bytes(data)
        path.chmod(0o600)
        return str(path)

    def cert(name, ca_cert=None, ca_key=None, ca=False):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_cert.subject if ca_cert else subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        )
        if name == "server":
            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False
            )
        if not ca:
            builder = builder.add_extension(
                x509.ExtendedKeyUsage(
                    [ExtendedKeyUsageOID.SERVER_AUTH if name == "server" else ExtendedKeyUsageOID.CLIENT_AUTH]
                ),
                critical=False,
            )
        signed = builder.sign(ca_key or key, hashes.SHA256())
        paths = (
            write(name + ".pem", signed.public_bytes(serialization.Encoding.PEM)),
            write(
                name + "-key.pem",
                key.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                ),
            ),
        )
        return signed, key, paths

    ca, ca_key, ca_paths = cert("ca", ca=True)
    _, _, server_paths = cert("server", ca, ca_key)
    client, _, client_paths = cert("client", ca, ca_key)
    _, _, other_paths = cert("other", ca, ca_key)
    server_tls = {
        "ca_file": ca_paths[0],
        "cert_file": server_paths[0],
        "key_file": server_paths[1],
        "peers": {
            hashlib.sha256(client.public_bytes(serialization.Encoding.DER)).hexdigest(): {
                "sources": ["127.0.0.1"],
                "result_writer": False,
            }
        },
    }
    config["tls"] = server_tls
    server.socket = tls_context(server_tls, server=True).wrap_socket(server.socket, server_side=True)
    client_tls = {"ca_file": ca_paths[0], "cert_file": client_paths[0], "key_file": client_paths[1]}
    client_path = write("client.json", json.dumps(client_tls).encode())
    context = tls_context(client_tls)
    other_context = tls_context({**client_tls, "cert_file": other_paths[0], "key_file": other_paths[1]})
    anonymous = ssl.create_default_context(cafile=ca_paths[0])
    return SimpleNamespace(
        context=context,
        other=other_context,
        anonymous=anonymous,
        client_path=client_path,
        connection=lambda: HTTPSConnection("127.0.0.1", server.server_port, context=context, timeout=5),
    )
