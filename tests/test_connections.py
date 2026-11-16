import base64
import ipaddress
import json
import socket
import ssl
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import paramiko
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from backend import store, tools


class SSHFixture(paramiko.ServerInterface):
    def __init__(self):
        self.command = None
        self.ready = threading.Event()

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if username == "sre-test" and password == "test-password" else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        self.command = command.decode()
        self.ready.set()
        return True


@pytest.fixture
def ssh_server():
    key = paramiko.RSAKey.generate(2048)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(10)
    listener.settimeout(0.2)
    port = listener.getsockname()[1]
    stop = threading.Event()
    seen = []
    transports = []
    def serve():
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            def session(connection):
                transport = paramiko.Transport(connection)
                transports.append(transport)
                transport.add_server_key(key)
                fixture = SSHFixture()
                try:
                    transport.start_server(server=fixture)
                    channel = transport.accept(3)
                    if channel is None or not fixture.ready.wait(3):
                        return
                    seen.append(fixture.command)
                    channel.send(b"Linux EarthAI protocol-test\n")
                    channel.send_stderr(b"test diagnostic stderr\n")
                    channel.send_exit_status(0)
                    channel.shutdown_write()
                except (EOFError, paramiko.SSHException, OSError):
                    pass
                finally:
                    transport.close()
            threading.Thread(target=session, args=(connection,), daemon=True).start()
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    config = {"kind": "ssh", "host": "127.0.0.1", "port": port, "username": "sre-test", "auth_type": "password", "password": store.seal("test-password"), "fingerprint": tools.fingerprint(key)}
    yield config, seen
    stop.set()
    listener.close()
    for transport in transports:
        transport.close()
    thread.join(timeout=2)


def test_real_ssh_protocol_and_host_pinning(ssh_server):
    server, seen = ssh_server
    result = tools.ssh_command(server, "uname -a", 5)
    assert result["exit_code"] == 0
    assert "EarthAI protocol-test" in result["stdout"]
    assert "diagnostic stderr" in result["stderr"]
    assert seen == ["uname -a"]
    with pytest.raises(tools.ToolError, match="指纹"):
        tools.ssh_command({**server, "fingerprint": ""}, "uname -a", 5)
    assert seen == ["uname -a"]


def test_real_ssh_emits_actual_output_chunks(ssh_server):
    server, _ = ssh_server
    events = []
    token = tools.TOOL_EVENTS.set(lambda stream, data: events.append((stream, data)))
    try:
        result = tools.ssh_command(server, "uname -a", 5)
    finally:
        tools.TOOL_EVENTS.reset(token)
    assert result["exit_code"] == 0
    assert any(stream == "progress" and "SSH" in data["content"] for stream, data in events)
    assert any(stream == "stdout" and "EarthAI protocol-test" in data["content"] for stream, data in events)
    assert any(stream == "stderr" and "diagnostic stderr" in data["content"] for stream, data in events)


@pytest.fixture
def kube_server(tmp_path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EarthAI Test CA")])
    stamp = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(private_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(stamp - timedelta(days=1)).not_valid_after(stamp + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(private_key, hashes.SHA256()))
    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    cert_path = tmp_path / "server.crt"
    key_path = tmp_path / "server.key"
    cert_path.write_bytes(cert_bytes)
    key_path.write_bytes(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def dispatch(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length)) if length else None
            seen.append({"method": self.command, "path": self.path, "body": body, "auth": self.headers.get("Authorization"), "type": self.headers.get("Content-Type")})
            if self.headers.get("Authorization") != "Bearer protocol-test-token":
                self.send_response(401)
                self.end_headers()
                return
            if self.path == "/version":
                result = {"gitVersion": "v1.test"}
            elif "/log" in self.path:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"application healthy\n")
                return
            else:
                result = {"kind": "PodList", "items": [{"metadata": {"name": "api", "managedFields": ["hidden"]}, "status": {"phase": "Running"}}], "data": {"sensitive": "hidden"}}
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        do_GET = dispatch
        do_PATCH = dispatch
        do_DELETE = dispatch
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path), str(key_path))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {"current-context": "test", "contexts": [{"name": "test", "context": {"cluster": "test", "user": "sre", "namespace": "production"}}],
        "clusters": [{"name": "test", "cluster": {"server": f"https://127.0.0.1:{server.server_port}", "certificate-authority-data": base64.b64encode(cert_bytes).decode()}}],
        "users": [{"name": "sre", "user": {"token": "protocol-test-token"}}]}
    yield {"kind": "kubernetes", "kubeconfig": store.seal(json.dumps(config))}, seen
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_real_tls_kubernetes_read_write_contract(kube_server):
    server, seen = kube_server
    result = tools.test_server(server)
    assert result["ok"] is True
    pods = tools.kube_operation(server, {"action": "list", "resource": "pods", "namespace": "*"})
    assert pods["items"][0]["status"]["phase"] == "Running"
    assert "data" not in pods
    assert "managedFields" not in pods["items"][0]["metadata"]
    assert "/api/v1/pods?" in seen[-1]["path"]
    logs = tools.kube_operation(server, {"action": "logs", "resource": "pods", "name": "api"})
    assert "application healthy" in logs["logs"]
    assert "/namespaces/production/pods/api/log?" in seen[-1]["path"]
    tools.kube_operation(server, {"action": "scale", "resource": "deployments", "name": "api", "replicas": 3})
    assert seen[-1]["method"] == "PATCH"
    assert seen[-1]["path"] == "/apis/apps/v1/namespaces/production/deployments/api/scale"
    assert seen[-1]["body"] == {"spec": {"replicas": 3}}
    tools.kube_operation(server, {"action": "apply", "resource": "deployments", "namespace": "production", "manifest": {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "api"}, "spec": {"replicas": 2}}})
    assert seen[-1]["method"] == "PATCH"
    assert seen[-1]["type"] == "application/apply-patch+yaml"
    assert "fieldManager=earthai" in seen[-1]["path"]
    with pytest.raises(tools.ToolError):
        tools.kube_operation(server, {"action": "get", "resource": "pods", "name": "../../secrets"})
    assert all(request["auth"] == "Bearer protocol-test-token" for request in seen)


def test_cancel_during_ssh_handshake_prevents_command(ssh_server, monkeypatch):
    server, seen = ssh_server
    cancellation = tools.Cancellation()
    context = tools.CANCELLATION.set(cancellation)
    original_connect = tools.ssh_connect
    def delayed_connect(config):
        connection = original_connect(config)
        cancellation.cancel()
        return connection
    monkeypatch.setattr(tools, "ssh_connect", delayed_connect)
    try:
        with pytest.raises(tools.ToolError, match="取消"):
            tools.ssh_command(server, "touch /tmp/should-not-execute", 5)
        assert not seen
    finally:
        tools.CANCELLATION.reset(context)


def stored_ssh_fixture(server):
    owner = store.uid()
    with store.connect() as db:
        db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (owner, owner + '@ssh.example', 'unused', '{}', store.now()))
    saved = store.save_entity(owner, 'servers', {**server, 'fingerprint': '', 'trust_on_first_use': True})
    return owner, saved


def test_first_ssh_key_auto_trust_is_persisted_and_not_repeated(ssh_server):
    server, seen = ssh_server
    owner, saved = stored_ssh_fixture(server)
    assert tools.ssh_command(saved, 'uname -a', 5)['exit_code'] == 0
    pinned = store.get_entity(owner, 'servers', saved['id'])
    assert pinned['fingerprint'] == server['fingerprint']
    assert pinned['fingerprint_trusted_at']
    assert tools.ssh_command(pinned, 'uname -a', 5)['exit_code'] == 0
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE owner=? AND action='server.fingerprint.trust_first'", (owner,)).fetchone()[0] == 1
    assert seen == ['uname -a', 'uname -a']


def test_auto_trust_does_not_replace_changed_or_manually_pinned_key(ssh_server):
    server, seen = ssh_server
    owner, saved = stored_ssh_fixture(server)
    saved['fingerprint'] = 'SHA256:' + 'A' * 43
    store.save_entity(owner, 'servers', saved, saved['id'])
    with pytest.raises(tools.ToolError, match='指纹'):
        tools.ssh_command(saved, 'uname -a', 5)
    assert store.get_entity(owner, 'servers', saved['id'])['fingerprint'] == saved['fingerprint']
    assert seen == []


def test_no_tofu_when_disabled_or_target_was_edited(ssh_server):
    server, seen = ssh_server
    owner, saved = stored_ssh_fixture(server)
    saved['trust_on_first_use'] = False
    store.save_entity(owner, 'servers', saved, saved['id'])
    with pytest.raises(tools.ToolError, match='指纹'):
        tools.ssh_command(saved, 'uname -a', 5)
    saved['trust_on_first_use'] = True
    store.save_entity(owner, 'servers', {**saved, 'host': '192.0.2.10'}, saved['id'])
    with pytest.raises(tools.ToolError, match='目标已变化'):
        tools.ssh_command(saved, 'uname -a', 5)
    assert seen == []

