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

if [[ ! -d /opt/ironman-prefect/radar-src/.git ]]; then
  echo "RADAR_SOURCE_REPO_MISSING"
  exit 4
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
  exit 5
fi

runuser -u ironmanprefect -- env   PREFECT_API_URL=http://127.0.0.1:4200/api   PREFECT_HOME=/var/lib/ironman-prefect   "$PREFECT_BIN" --no-prompt deploy   --prefect-file /opt/ironman-prefect/radar-src/prefect/ironman-coaching-radar-v2.yaml   --name alberto-group-readonly-daily

PYTHON_BIN="$(dirname "$PREFECT_BIN")/python"
runuser -u ironmanprefect -- env   PREFECT_API_URL=http://127.0.0.1:4200/api   PREFECT_HOME=/var/lib/ironman-prefect   "$PYTHON_BIN" /opt/ironman-prefect/radar-src/scripts/ironman_jobs/verify_coaching_radar_group_staging_20261017.py   --as-of "$AS_OF"

echo "COACHING_RADAR_GROUP_STAGING_INSTALL_PASS"
