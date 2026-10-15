#!/usr/bin/env bash
# IRONMAN: isolated Prefect 3.8.8 single-worker staging for an Ubuntu 24.04
# DigitalOcean Droplet. No TrainingPeaks credentials/calls; API localhost only.
set -Eeuo pipefail
umask 077
trap 'r=$?; echo "PREFECT_STAGING_BOOTSTRAP_FAIL exit=$r line=$LINENO" >&2; exit "$r"' ERR
if [[ "$(id -u)" != 0 ]]; then echo "SAFE_STOP: root required" >&2; exit 2; fi
source /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 24.04 || "$(uname -m)" != x86_64 ]]; then
  echo "SAFE_STOP: expected isolated Ubuntu 24.04 x86_64" >&2; exit 3
fi
if [[ -e /etc/systemd/system/ironman-trainingpeaks-tunnel.service ]]; then
  echo "SAFE_STOP: refusing to install on the existing TrainingPeaks Droplet" >&2; exit 4
fi

readonly U=ironmanprefect
readonly D=/var/lib/ironman-prefect
readonly V=/opt/ironman-prefect/venv
readonly API=http://127.0.0.1:4200/api
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl python3.12-venv python3-pip iproute2
if ! id "$U" >/dev/null 2>&1; then
  useradd --system --user-group --home-dir "$D" --create-home --shell /usr/sbin/nologin "$U"
fi
install -d -o root -g root -m 0755 /opt/ironman-prefect
install -d -o "$U" -g "$U" -m 0700 "$D"
if [[ ! -x "$V/bin/python" ]]; then python3.12 -m venv "$V"; fi
"$V/bin/python" -m pip install --disable-pip-version-check --no-cache-dir "prefect==3.8.8"

cat > /etc/systemd/system/ironman-prefect-server.service <<'UNIT'
[Unit]
Description=IRONMAN Prefect staging API (localhost only)
Wants=network-online.target
After=network-online.target
[Service]
Type=simple
User=ironmanprefect
Group=ironmanprefect
WorkingDirectory=/var/lib/ironman-prefect
Environment=HOME=/var/lib/ironman-prefect
Environment=PREFECT_HOME=/var/lib/ironman-prefect
Environment=PREFECT_API_URL=http://127.0.0.1:4200/api
Environment=PREFECT_SERVER_ANALYTICS_ENABLED=false
Environment=PREFECT_CLOUD_ENABLE_ORCHESTRATION_TELEMETRY=false
Environment=PREFECT_LOGGING_LEVEL=WARNING
ExecStart=/opt/ironman-prefect/venv/bin/python -m prefect server start --host 127.0.0.1 --port 4200
Restart=on-failure
RestartSec=6
TimeoutStopSec=40
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
StateDirectory=ironman-prefect
ReadWritePaths=/var/lib/ironman-prefect
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/ironman-prefect-worker.service <<'UNIT'
[Unit]
Description=IRONMAN Prefect staging worker (concurrency 1)
Wants=network-online.target ironman-prefect-server.service
After=network-online.target ironman-prefect-server.service
[Service]
Type=simple
User=ironmanprefect
Group=ironmanprefect
WorkingDirectory=/var/lib/ironman-prefect
Environment=HOME=/var/lib/ironman-prefect
Environment=PREFECT_HOME=/var/lib/ironman-prefect
Environment=PREFECT_API_URL=http://127.0.0.1:4200/api
Environment=PREFECT_SERVER_ANALYTICS_ENABLED=false
Environment=PREFECT_CLOUD_ENABLE_ORCHESTRATION_TELEMETRY=false
Environment=PREFECT_LOGGING_LEVEL=WARNING
ExecStart=/opt/ironman-prefect/venv/bin/python -m prefect worker start --pool ironman-staging --type process --name ironman-staging-worker --limit 1 --install-policy never
Restart=always
RestartSec=10
TimeoutStopSec=40
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
StateDirectory=ironman-prefect
ReadWritePaths=/var/lib/ironman-prefect
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now ironman-prefect-server.service
curl --max-time 3 --retry 45 --retry-delay 2 --retry-connrefused -fsS "$API/health" >/dev/null
as_user() {
  runuser -u "$U" -- env HOME="$D" PREFECT_HOME="$D" PREFECT_API_URL="$API" \
    PREFECT_SERVER_ANALYTICS_ENABLED=false PREFECT_CLOUD_ENABLE_ORCHESTRATION_TELEMETRY=false "$@"
}
if ! as_user "$V/bin/python" -m prefect work-pool inspect ironman-staging >/dev/null 2>&1; then
  as_user "$V/bin/python" -m prefect work-pool create ironman-staging --type process
fi
systemctl enable --now ironman-prefect-worker.service
sleep 5
systemctl is-active --quiet ironman-prefect-server.service
systemctl is-active --quiet ironman-prefect-worker.service
curl --max-time 4 -fsS "$API/health" >/dev/null
if ss -ltnH | awk '$4 ~ /:4200$/ {print $4}' | grep -Ev '^(127\.0\.0\.1:4200|\[::1\]:4200)$' >/dev/null; then
  systemctl stop ironman-prefect-worker.service ironman-prefect-server.service || true
  echo "SAFE_STOP: Prefect API must not listen on the public interface" >&2; exit 11
fi

echo "PREFECT_STAGING_BOOTSTRAP_PASS"
echo "server=$(systemctl is-active ironman-prefect-server.service)"
echo "worker=$(systemctl is-active ironman-prefect-worker.service)"
echo "server_mem_bytes=$(systemctl show -p MemoryCurrent --value ironman-prefect-server.service)"
echo "worker_mem_bytes=$(systemctl show -p MemoryCurrent --value ironman-prefect-worker.service)"
awk '/MemTotal:|MemAvailable:|SwapTotal:/{print $1, $2, $3}' /proc/meminfo
echo "api=127.0.0.1:4200 only"
echo "trainingpeaks_writes=0 production_ledger_access=false"
echo "STATUS=STAGING_BOOTSTRAPPED_NOT_PRODUCTION"
