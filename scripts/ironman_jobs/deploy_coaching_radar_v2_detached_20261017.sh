#!/usr/bin/env bash
set -euo pipefail

REVISION="${1:-}"
AS_OF="${2:-}"
REPO=/opt/ironman-prefect/radar-src
LOG=/var/log/ironman-radar-v2-deploy.log

exec >>"$LOG" 2>&1
echo "RADAR_V2_DETACHED_START $(date -u +%FT%TZ) revision=$REVISION as_of=$AS_OF"

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

OWNER_HOME="$(getent passwd ironmanprefect | cut -d: -f6)"
if [[ -z "$OWNER_HOME" || ! -d "$OWNER_HOME" ]]; then
  echo "OWNER_HOME_NOT_FOUND"
  exit 6
fi

runuser -u ironmanprefect -- env HOME="$OWNER_HOME" git -C "$REPO" fetch --no-tags origin lab/ironman-prefect-20261015
runuser -u ironmanprefect -- env HOME="$OWNER_HOME" git -C "$REPO" checkout --detach "$REVISION"
ACTUAL="$(runuser -u ironmanprefect -- env HOME="$OWNER_HOME" git -C "$REPO" rev-parse HEAD)"
if [[ "$ACTUAL" != "$REVISION" ]]; then
  echo "REVISION_MISMATCH actual=$ACTUAL expected=$REVISION"
  exit 4
fi

# Prefect resolves entrypoints relative to the command working directory.
# A detached systemd run or a root console must not inherit / or /root here.
cd "$REPO"

PREFECT_BIN="$(systemctl show -p ExecStart --value ironman-prefect-worker.service | grep -oE '/[^ ;]+/prefect' | head -n1 || true)"
if [[ -z "$PREFECT_BIN" || ! -x "$PREFECT_BIN" ]]; then
  PREFECT_BIN="$(command -v prefect || true)"
fi
if [[ -z "$PREFECT_BIN" || ! -x "$PREFECT_BIN" ]]; then
  echo "PREFECT_BIN_NOT_FOUND"
  exit 5
fi

for NAME in polverari-readonly-daily-v2 alberto-group-readonly-daily; do
  runuser -u ironmanprefect -- env HOME="$OWNER_HOME" \
    PREFECT_API_URL=http://127.0.0.1:4200/api \
    PREFECT_HOME=/var/lib/ironman-prefect \
    "$PREFECT_BIN" --no-prompt deploy \
    --prefect-file "$REPO/prefect/ironman-coaching-radar-v2.yaml" \
    --name "$NAME"
done

PYTHON_BIN="$(dirname "$PREFECT_BIN")/python"
runuser -u ironmanprefect -- env HOME="$OWNER_HOME" \
  PREFECT_API_URL=http://127.0.0.1:4200/api \
  PREFECT_HOME=/var/lib/ironman-prefect \
  "$PYTHON_BIN" \
  "$REPO/scripts/ironman_jobs/verify_coaching_radar_group_staging_20261017.py" \
  --as-of "$AS_OF"

echo "RADAR_V2_DETACHED_DEPLOY_PASS $(date -u +%FT%TZ)"
