"""Schedule one controlled restart of the TrainingPeaks MCP tunnel service.

No TrainingPeaks provider writes. The repo is already pinned/checked out by the
operator before this script runs. A detached helper sends SIGTERM to the
tunnel-client main process after this script exits; systemd Restart=always
brings the service back with the current checkout.
"""
import os
import subprocess
from pathlib import Path

EXPECTED_HOST = "ironman-tp-mcp"


def cmdline(pid: int) -> str:
    return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode().strip()


if os.uname().nodename != EXPECTED_HOST:
    raise RuntimeError("WRONG_HOST")

server_pid = os.getppid()
server_cmd = cmdline(server_pid)
if "tp-mcp serve" not in server_cmd:
    raise RuntimeError("PARENT_NOT_TP_MCP")

stat = Path(f"/proc/{server_pid}/stat").read_text().split()
tunnel_pid = int(stat[3])
tunnel_cmd = cmdline(tunnel_pid)
if "tunnel-client run --profile trainingpeaks" not in tunnel_cmd:
    raise RuntimeError("GRANDPARENT_NOT_TUNNEL")

helper = (
    "sleep 2; "
    f"kill -TERM {tunnel_pid}"
)
subprocess.Popen(
    ["/bin/sh", "-c", helper],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
    close_fds=True,
)
print(f"MCP_RELOAD_SCHEDULED tunnel_pid={tunnel_pid} server_pid={server_pid}")
