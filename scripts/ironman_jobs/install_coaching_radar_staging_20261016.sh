#!/usr/bin/env bash
set -euo pipefail

REVISION="${1:-}"
AS_OF="${2:-}"
if [[ ! "$REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  echo "REVISION_REQUIRED"
  exit 2
fi
if [[ ! "$AS_OF" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "AS_OF_REQUIRED"
  exit 2
fi

if [[ "$(hostname)" != "ironman-prefect-staging" ]]; then
  echo "WRONG_HOST"
  exit 3
fi

systemctl is-active --quiet ironman-prefect-server.service
systemctl is-active --quiet ironman-prefect-worker.service

HEALTH="$(curl --fail --silent --max-time 10 http://10.114.0.2:8787/health)"
python3 -c 'import json,sys; x=json.loads(sys.argv[1]); assert x["mode"]=="READ_ONLY"' "$HEALTH"

install -d -m 0755 -o ironmanprefect -g ironmanprefect /opt/ironman-prefect/radar-src
if [[ ! -d /opt/ironman-prefect/radar-src/.git ]]; then
  rm -rf /opt/ironman-prefect/radar-src
  git clone --no-tags --single-branch --branch lab/ironman-prefect-20261015     https://github.com/Publimage/trainingpeaks-mcp.git /opt/ironman-prefect/radar-src
fi
cd /opt/ironman-prefect/radar-src
git fetch --no-tags origin lab/ironman-prefect-20261015
git checkout --detach "$REVISION"
[[ "$(git rev-parse HEAD)" == "$REVISION" ]]
chown -R ironmanprefect:ironmanprefect /opt/ironman-prefect/radar-src

PREFECT_BIN="$(systemctl show -p ExecStart --value ironman-prefect-worker.service | grep -oE '/[^ ;]+/prefect' | head -n1 || true)"
if [[ -z "$PREFECT_BIN" || ! -x "$PREFECT_BIN" ]]; then
  PREFECT_BIN="$(command -v prefect || true)"
fi
if [[ -z "$PREFECT_BIN" || ! -x "$PREFECT_BIN" ]]; then
  echo "PREFECT_BIN_NOT_FOUND"
  exit 4
fi

install -d -m 0700 -o ironmanprefect -g ironmanprefect /var/lib/ironman-prefect/radar

runuser -u ironmanprefect -- env   PREFECT_API_URL=http://127.0.0.1:4200/api   PREFECT_HOME=/var/lib/ironman-prefect   "$PREFECT_BIN" --no-prompt deploy   --prefect-file /opt/ironman-prefect/radar-src/prefect/ironman-coaching-radar-v1.yaml   --name polverari-readonly-pilot

PYTHON_BIN="$(dirname "$PREFECT_BIN")/python"
runuser -u ironmanprefect -- env   PREFECT_API_URL=http://127.0.0.1:4200/api   PREFECT_HOME=/var/lib/ironman-prefect   "$PYTHON_BIN" /opt/ironman-prefect/radar-src/scripts/ironman_jobs/verify_coaching_radar_staging_20261016.py   --as-of "$AS_OF"

echo "COACHING_RADAR_STAGING_INSTALL_PASS"
