#!/usr/bin/env bash
set -euo pipefail

REVISION="${1:-}"
REPO=/opt/ironman-prefect/radar-src
RUNTIME=/opt/ironman-prefect/drive-reader
VENV="$RUNTIME/venv"
CREDENTIAL_DIR=/var/lib/ironman-prefect/credentials

if [[ ! "$REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  echo "REVISION_REQUIRED"
  exit 2
fi
if [[ "$(hostname)" != "ironman-prefect-staging" ]]; then
  echo "WRONG_HOST"
  exit 3
fi
systemctl is-active --quiet ironman-prefect-server.service
systemctl is-active --quiet ironman-prefect-worker.service

OWNER_HOME="$(getent passwd ironmanprefect | cut -d: -f6)"
if [[ -z "$OWNER_HOME" || ! -d "$OWNER_HOME" ]]; then
  echo "OWNER_HOME_NOT_FOUND"
  exit 4
fi

ACTUAL="$(runuser -u ironmanprefect -- env HOME="$OWNER_HOME" git -C "$REPO" rev-parse HEAD)"
if [[ "$ACTUAL" != "$REVISION" ]]; then
  echo "REVISION_MISMATCH actual=$ACTUAL expected=$REVISION"
  exit 5
fi

install -d -m 0750 -o ironmanprefect -g ironmanprefect "$RUNTIME"
install -d -m 0700 -o ironmanprefect -g ironmanprefect "$CREDENTIAL_DIR"

if [[ ! -x "$VENV/bin/python" ]]; then
  runuser -u ironmanprefect -- env HOME="$OWNER_HOME" python3 -m venv "$VENV"
fi

runuser -u ironmanprefect -- env HOME="$OWNER_HOME"   "$VENV/bin/python" -m pip install --disable-pip-version-check   "google-auth[requests]==2.62.0"

runuser -u ironmanprefect -- env HOME="$OWNER_HOME"   PYTHONPATH="$REPO" "$VENV/bin/python" -c   'from scripts.ironman_jobs.coaching_radar_drive_context_adapter_v0 import DRIVE_READONLY_SCOPE; assert DRIVE_READONLY_SCOPE == "https://www.googleapis.com/auth/drive.readonly"; import google.auth; print("RADAR_DRIVE_READER_RUNTIME_PASS")'

echo "RADAR_DRIVE_CREDENTIAL_DIR=$CREDENTIAL_DIR"
echo "RADAR_DRIVE_READER_PREPARE_PASS"
