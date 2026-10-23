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

RAW="https://raw.githubusercontent.com/Publimage/trainingpeaks-mcp/${REVISION}/scripts/ironman_jobs/prefect_private_admin_api.py"
curl -fsSL "$RAW" -o /usr/local/sbin/ironman-prefect-private-admin
chown root:root /usr/local/sbin/ironman-prefect-private-admin
chmod 0755 /usr/local/sbin/ironman-prefect-private-admin
python3 -m py_compile /usr/local/sbin/ironman-prefect-private-admin

install -d -m 0700 -o root -g root /var/lib/ironman-prefect/private-admin-api

cat >/etc/systemd/system/ironman-prefect-private-admin.service <<'EOF'
[Unit]
Description=IRONMAN Prefect private typed admin API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
ExecStart=/usr/bin/python3 /usr/local/sbin/ironman-prefect-private-admin
Restart=on-failure
RestartSec=3
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
UMask=0077

[Install]
WantedBy=multi-user.target
EOF

systemd-analyze verify /etc/systemd/system/ironman-prefect-private-admin.service
systemctl daemon-reload
systemctl enable --now ironman-prefect-private-admin.service

ufw status | grep -qE '8790.*10\.114\.0\.2' ||   ufw allow from 10.114.0.2 to 10.114.0.3 port 8790 proto tcp comment 'TP private admin bridge'

systemctl disable --now ironman-prefect-admin-pull.timer >/dev/null 2>&1 || true
systemctl stop ironman-prefect-admin-pull.service >/dev/null 2>&1 || true

systemctl is-active --quiet ironman-prefect-private-admin.service
curl -fsS --connect-timeout 5 http://10.114.0.3:8790/health >/dev/null
echo "PREFECT_PRIVATE_ADMIN_API_BOOTSTRAP_PASS"
