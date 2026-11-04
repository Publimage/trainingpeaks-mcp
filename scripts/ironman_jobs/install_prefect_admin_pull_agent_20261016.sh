#!/usr/bin/env bash
set -euo pipefail

REVISION="${1:-}"
if [[ ! "$REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  echo "PINNED_REVISION_REQUIRED"
  exit 2
fi
if [[ "$(hostname)" != "ironman-prefect-staging" ]]; then
  echo "WRONG_HOST"
  exit 3
fi

RAW_BASE="https://raw.githubusercontent.com/Publimage/trainingpeaks-mcp/${REVISION}"
AGENT_URL="${RAW_BASE}/scripts/ironman_jobs/prefect_admin_pull_agent.py"

install -d -m 0700 -o root -g root /var/lib/ironman-prefect/admin-agent
curl --fail --silent --show-error --location "$AGENT_URL" -o /usr/local/sbin/ironman-prefect-admin-pull
chown root:root /usr/local/sbin/ironman-prefect-admin-pull
chmod 0755 /usr/local/sbin/ironman-prefect-admin-pull
python3 -m py_compile /usr/local/sbin/ironman-prefect-admin-pull

cat >/etc/systemd/system/ironman-prefect-admin-pull.service <<'EOF'
[Unit]
Description=IRONMAN Prefect private admin pull agent
After=network-online.target ironman-prefect-server.service
Wants=network-online.target

[Service]
Type=oneshot
User=root
Group=root
ExecStart=/usr/bin/python3 /usr/local/sbin/ironman-prefect-admin-pull
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/var/lib/ironman-prefect /opt/ironman-prefect /etc/systemd/system
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
UMask=0077
EOF

cat >/etc/systemd/system/ironman-prefect-admin-pull.timer <<'EOF'
[Unit]
Description=Poll IRONMAN Prefect admin manifest

[Timer]
OnBootSec=20s
OnUnitActiveSec=30s
AccuracySec=5s
Persistent=true
Unit=ironman-prefect-admin-pull.service

[Install]
WantedBy=timers.target
EOF

systemd-analyze verify   /etc/systemd/system/ironman-prefect-admin-pull.service   /etc/systemd/system/ironman-prefect-admin-pull.timer
systemctl daemon-reload
systemctl enable --now ironman-prefect-admin-pull.timer
systemctl start ironman-prefect-admin-pull.service
systemctl is-enabled --quiet ironman-prefect-admin-pull.timer
systemctl is-active --quiet ironman-prefect-admin-pull.timer

echo "PREFECT_PRIVATE_ADMIN_AGENT_BOOTSTRAP_PASS"
