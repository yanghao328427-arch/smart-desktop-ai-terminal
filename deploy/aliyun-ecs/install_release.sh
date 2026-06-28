#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:-/tmp/smartdesk-ecs-release.tar.gz}"
APP_ROOT="/opt/smartdesk"
DATA_ROOT="/var/lib/smartdesk"
ENV_FILE="/etc/smartdesk.env"
SERVICE_FILE="/etc/systemd/system/voice-iot.service"
NGINX_FILE="/etc/nginx/sites-available/voice-iot"
RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_ID"
BACKUP_DIR="/root/voice-iot-backup-$RELEASE_ID"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run this installer as root." >&2
  exit 1
fi
if [[ ! -f "$ARCHIVE" ]]; then
  echo "ERROR: release archive not found: $ARCHIVE" >&2
  exit 1
fi

echo "[1/8] Backing up the current service and Nginx configuration..."
mkdir -p "$BACKUP_DIR"
[[ -f "$SERVICE_FILE" ]] && cp -a "$SERVICE_FILE" "$BACKUP_DIR/voice-iot.service"
[[ -f "$NGINX_FILE" ]] && cp -a "$NGINX_FILE" "$BACKUP_DIR/nginx-voice-iot"
[[ -f /root/voice-iot-server/main.py ]] && cp -a /root/voice-iot-server/main.py "$BACKUP_DIR/main.py"
[[ -L "$APP_ROOT/current" ]] && readlink -f "$APP_ROOT/current" >"$BACKUP_DIR/previous-release"

echo "[2/8] Creating the service account and persistent data directory..."
if ! id smartdesk >/dev/null 2>&1; then
  useradd --system --home "$APP_ROOT" --shell /usr/sbin/nologin smartdesk
fi
mkdir -p "$APP_ROOT/releases" "$DATA_ROOT/audio" "$DATA_ROOT/audio_chunks"
chown -R smartdesk:smartdesk "$DATA_ROOT"

echo "[3/8] Extracting release $RELEASE_ID..."
mkdir -p "$RELEASE_DIR"
tar -xzf "$ARCHIVE" -C "$RELEASE_DIR"
ln -sfn "$DATA_ROOT" "$RELEASE_DIR/backend/data"
chown -R root:root "$RELEASE_DIR"
ln -sfn "$RELEASE_DIR" "$APP_ROOT/current"

echo "[4/8] Installing Python dependencies..."
PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$(printf '%s\n' "3.10" "$PYTHON_VERSION" | sort -V | head -n1)" != "3.10" ]]; then
  echo "ERROR: Python 3.10 or newer is required; found $PYTHON_VERSION." >&2
  exit 1
fi
if [[ ! -x "$APP_ROOT/venv/bin/python" ]]; then
  python3 -m venv "$APP_ROOT/venv"
fi
"$APP_ROOT/venv/bin/python" -m pip install --upgrade pip
"$APP_ROOT/venv/bin/pip" install -r "$RELEASE_DIR/backend/requirements.txt"

echo "[5/8] Preparing server-only environment configuration..."
if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f /root/voice-iot-server/.env ]]; then
    install -m 600 /root/voice-iot-server/.env "$ENV_FILE"
  else
    CONTROL_TOKEN="$(openssl rand -hex 24)"
    DEVICE_TOKEN="$(openssl rand -hex 24)"
    cat >"$ENV_FILE" <<EOF
APP_NAME=Smart Desktop AI Terminal
DEVICE_ID=desktop-agent-001
EDGE_ID=esp32s3-sense-001
AI_PROVIDER=mock
AI_MODEL=qwen-plus
ASR_PROVIDER=dashscope_paraformer
ASR_MODEL=paraformer-realtime-v2
ASR_LANGUAGE_HINT=zh
CONTROL_TOKEN=$CONTROL_TOKEN
DEVICE_TOKEN=$DEVICE_TOKEN
CONTEXT_DB_PATH=$DATA_ROOT/context.sqlite3
RFID_REGISTRY_PATH=$DATA_ROOT/rfid_users.json
EOF
    chmod 600 "$ENV_FILE"
    echo "NOTICE: $ENV_FILE was created with generated control/device tokens."
    echo "NOTICE: add DASHSCOPE_API_KEY and set AI_PROVIDER=dashscope_openai to enable cloud AI."
  fi
fi

echo "[6/8] Installing the single-worker systemd service..."
cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Smart Desktop AI Terminal FastAPI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=smartdesk
Group=smartdesk
WorkingDirectory=$APP_ROOT/current/backend
EnvironmentFile=$ENV_FILE
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_ROOT/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=3
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF

echo "[7/8] Installing Nginx HTTP and WebSocket proxy configuration..."
TLS_DOMAIN="8-163-38-158.sslip.io"
if [[ -f "/etc/letsencrypt/live/$TLS_DOMAIN/fullchain.pem" ]]; then
cat >"$NGINX_FILE" <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name 8.163.38.158 $TLS_DOMAIN _;

    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        proxy_buffering off;
    }
}
EOF
cat >>"$NGINX_FILE" <<EOF

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name $TLS_DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$TLS_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$TLS_DOMAIN/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        proxy_buffering off;
    }
}
EOF
else
cat >"$NGINX_FILE" <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name 8.163.38.158 _;

    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        proxy_buffering off;
    }
}
EOF
fi
ln -sfn "$NGINX_FILE" /etc/nginx/sites-enabled/voice-iot
rm -f /etc/nginx/sites-enabled/default
nginx -t

echo "[8/8] Restarting services and running smoke checks..."
systemctl daemon-reload
systemctl enable voice-iot
systemctl restart voice-iot
systemctl restart nginx

for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1/api/health >/tmp/smartdesk-health.json; then
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1/api/health
echo
curl -fsS http://127.0.0.1/api/state/desktop-agent-001 >/dev/null

cat >"/root/rollback-smartdesk-$RELEASE_ID.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ -f "$BACKUP_DIR/voice-iot.service" ]]; then
  cp -a "$BACKUP_DIR/voice-iot.service" "$SERVICE_FILE"
fi
if [[ -f "$BACKUP_DIR/nginx-voice-iot" ]]; then
  cp -a "$BACKUP_DIR/nginx-voice-iot" "$NGINX_FILE"
fi
if [[ -f "$BACKUP_DIR/previous-release" ]]; then
  ln -sfn "\$(cat "$BACKUP_DIR/previous-release")" "$APP_ROOT/current"
fi
systemctl daemon-reload
nginx -t
systemctl restart voice-iot
systemctl restart nginx
EOF
chmod 700 "/root/rollback-smartdesk-$RELEASE_ID.sh"

echo
echo "DEPLOYMENT_OK release=$RELEASE_ID"
echo "ENV_FILE=$ENV_FILE"
echo "BACKUP_DIR=$BACKUP_DIR"
echo "ROLLBACK=/root/rollback-smartdesk-$RELEASE_ID.sh"
echo "PUBLIC_HEALTH=http://8.163.38.158/api/health"
