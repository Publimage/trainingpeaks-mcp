"""Private read-only TrainingPeaks bridge for the Prefect staging VPC.

The bridge is disabled unless an explicit server-local JSON config exists.
It binds only to the configured private interface, accepts only allowlisted
source IPs and athlete IDs, and exposes one bounded read-only radar endpoint.
No TrainingPeaks write tools are imported or reachable here.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tp_mcp.client.context import athlete_override
from tp_mcp.tools.metrics import tp_get_metrics
from tp_mcp.tools.workouts import tp_get_workout, tp_get_workouts

DEFAULT_CONFIG = Path("/home/ironman/.config/ironman/private_bridge.json")
MAX_BODY_BYTES = 65536
ENDURANCE_SPORTS = {"Swim", "Bike", "Run", "Brick"}


class BridgeConfigError(RuntimeError):
    pass


def _load_config(path: Path | None = None) -> dict[str, Any] | None:
    config_path = path or Path(os.environ.get("IRONMAN_PRIVATE_BRIDGE_CONFIG", str(DEFAULT_CONFIG)))
    if not config_path.exists():
        return None
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    host = str(raw.get("host") or "").strip()
    port = int(raw.get("port") or 0)
    allowed_sources = {str(x).strip() for x in raw.get("allowed_sources", []) if str(x).strip()}
    allowed_athletes = {str(x).strip() for x in raw.get("allowed_athletes", []) if str(x).strip()}
    max_window_days = int(raw.get("max_window_days") or 0)
    if not host.startswith("10.") or not (1024 <= port <= 65535):
        raise BridgeConfigError("PRIVATE_BIND_REQUIRED")
    if not allowed_sources or not all(x.startswith("10.") for x in allowed_sources):
        raise BridgeConfigError("PRIVATE_SOURCE_ALLOWLIST_REQUIRED")
    if not allowed_athletes or not all(x.isdigit() for x in allowed_athletes):
        raise BridgeConfigError("ATHLETE_ALLOWLIST_REQUIRED")
    if not 1 <= max_window_days <= 31:
        raise BridgeConfigError("INVALID_MAX_WINDOW_DAYS")
    return {
        "host": host,
        "port": port,
        "allowed_sources": allowed_sources,
        "allowed_athletes": allowed_athletes,
        "max_window_days": max_window_days,
    }


def _validate_window(start_date: str, end_date: str, max_days: int) -> None:
    from datetime import date
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("END_BEFORE_START")
    if (end - start).days + 1 > max_days:
        raise ValueError("DATE_WINDOW_TOO_LARGE")


async def _build_radar_input(
    *,
    athlete_id: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    token = athlete_override.set(athlete_id)
    try:
        workouts_result = await tp_get_workouts(start_date, end_date, "all")
        if workouts_result.get("isError"):
            return workouts_result

        details: list[dict[str, Any]] = []
        for workout in workouts_result.get("workouts", []):
            if workout.get("type") != "completed" or workout.get("sport") not in ENDURANCE_SPORTS:
                continue
            detail = await tp_get_workout(str(workout["id"]))
            if detail.get("isError"):
                details.append({
                    "id": str(workout["id"]),
                    "isError": True,
                    "error_code": detail.get("error_code"),
                })
            else:
                details.append(detail)

        metrics_result = await tp_get_metrics(start_date, end_date)
        if metrics_result.get("isError"):
            metrics_result = {
                "metrics": [],
                "count": 0,
                "read_error": {
                    "error_code": metrics_result.get("error_code"),
                    "message": metrics_result.get("message"),
                },
            }

        return {
            "schema": "IRONMAN_TP_RADAR_INPUT_V1",
            "athlete_id": int(athlete_id),
            "start_date": start_date,
            "end_date": end_date,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "workouts": workouts_result.get("workouts", []),
            "completed_details": details,
            "metrics": metrics_result,
            "trainingpeaks_writes": 0,
        }
    finally:
        athlete_override.reset(token)


def _handler_factory(config: dict[str, Any]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "IRONMANPrivateBridge/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _write_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _source_allowed(self) -> bool:
            return str(self.client_address[0]) in config["allowed_sources"]

        def do_GET(self) -> None:
            if not self._source_allowed():
                self._write_json(403, {"error": "SOURCE_NOT_ALLOWED"})
                return
            if urlparse(self.path).path == "/health":
                self._write_json(200, {
                    "status": "ok",
                    "mode": "READ_ONLY",
                    "schema": "IRONMAN_PRIVATE_BRIDGE_V1",
                })
                return
            self._write_json(404, {"error": "NOT_FOUND"})

        def do_POST(self) -> None:
            if not self._source_allowed():
                self._write_json(403, {"error": "SOURCE_NOT_ALLOWED"})
                return
            if urlparse(self.path).path != "/v1/radar-input":
                self._write_json(404, {"error": "NOT_FOUND"})
                return
            try:
                length = int(self.headers.get("Content-Length") or "0")
                if length <= 0 or length > MAX_BODY_BYTES:
                    raise ValueError("INVALID_BODY_SIZE")
                payload = json.loads(self.rfile.read(length))
                athlete_id = str(payload["athlete_id"])
                if athlete_id not in config["allowed_athletes"]:
                    self._write_json(403, {"error": "ATHLETE_NOT_ALLOWED"})
                    return
                start_date = str(payload["start_date"])
                end_date = str(payload["end_date"])
                _validate_window(start_date, end_date, config["max_window_days"])
                result = asyncio.run(_build_radar_input(
                    athlete_id=athlete_id,
                    start_date=start_date,
                    end_date=end_date,
                ))
                status = 502 if result.get("isError") else 200
                self._write_json(status, result)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._write_json(400, {"error": "INVALID_REQUEST", "message": str(exc)})
            except Exception:
                self._write_json(500, {"error": "BRIDGE_INTERNAL_ERROR"})

    return Handler


class PrivateBridge:
    def __init__(self, server: ThreadingHTTPServer, thread: threading.Thread):
        self.server = server
        self.thread = thread

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def maybe_start_private_bridge(path: Path | None = None) -> PrivateBridge | None:
    config = _load_config(path)
    if config is None:
        return None
    server = ThreadingHTTPServer(
        (config["host"], config["port"]),
        _handler_factory(config),
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name="ironman-private-bridge",
        daemon=True,
    )
    thread.start()
    return PrivateBridge(server, thread)
