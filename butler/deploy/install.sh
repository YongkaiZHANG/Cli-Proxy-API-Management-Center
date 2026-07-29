#!/usr/bin/env bash
set -euo pipefail

PUBLIC_IP="${PUBLIC_IP:-112.74.109.99}"
APP_DIR="${APP_DIR:-/opt/cli-proxy-management}"
APP_USER="${APP_USER:-butler}"
REPO_URL="${REPO_URL:-https://github.com/YongkaiZHANG/Cli-Proxy-API-Management-Center.git}"
BRANCH="${BRANCH:-agent/butler-mvp}"
GATEWAY_BASE_URL="${BUTLER_GATEWAY_BASE_URL:-http://127.0.0.1:8317}"
GATEWAY_API_KEY="${BUTLER_GATEWAY_API_KEY:-}"
BASIC_USER="${BUTLER_BASIC_USER:-butler}"
BASIC_PASSWORD="${BUTLER_BASIC_PASSWORD:-}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo -E bash butler/deploy/install.sh" >&2
  exit 1
fi
if [[ -z "$GATEWAY_API_KEY" ]]; then
  echo "BUTLER_GATEWAY_API_KEY is required." >&2
  exit 1
fi
if [[ -z "$BASIC_PASSWORD" ]]; then
  echo "BUTLER_BASIC_PASSWORD is required." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git nginx apache2-utils python3 python3-venv python3-pip curl ca-certificates

if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

if [[ ! -d "$APP_DIR/.git" ]]; then
  rm -rf "$APP_DIR"
  git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch origin "$BRANCH"
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
fi

python3 -m venv "$APP_DIR/butler/.venv"
"$APP_DIR/butler/.venv/bin/pip" install --upgrade pip
"$APP_DIR/butler/.venv/bin/pip" install -r "$APP_DIR/butler/requirements.txt"

install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR/butler/data"
cat > "$APP_DIR/butler/.env" <<EOF
BUTLER_GATEWAY_BASE_URL=$GATEWAY_BASE_URL
BUTLER_GATEWAY_API_KEY=$GATEWAY_API_KEY
BUTLER_HOST=127.0.0.1
BUTLER_PORT=8318
BUTLER_DATABASE_PATH=$APP_DIR/butler/data/butler.db
EOF
chmod 600 "$APP_DIR/butler/.env"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/butler"

install -m 0644 "$APP_DIR/butler/deploy/butler.service" /etc/systemd/system/butler.service
sed -i "s|__APP_DIR__|$APP_DIR|g; s|__APP_USER__|$APP_USER|g" /etc/systemd/system/butler.service

htpasswd -bc /etc/nginx/.htpasswd-butler "$BASIC_USER" "$BASIC_PASSWORD"
chmod 640 /etc/nginx/.htpasswd-butler
chown root:www-data /etc/nginx/.htpasswd-butler

install -m 0644 "$APP_DIR/butler/deploy/nginx-http.conf" /etc/nginx/sites-available/butler
sed -i "s|__PUBLIC_IP__|$PUBLIC_IP|g" /etc/nginx/sites-available/butler
ln -sfn /etc/nginx/sites-available/butler /etc/nginx/sites-enabled/butler
rm -f /etc/nginx/sites-enabled/default
mkdir -p /var/www/letsencrypt/.well-known/acme-challenge

systemctl daemon-reload
systemctl enable --now butler
nginx -t
systemctl enable --now nginx
systemctl reload nginx

for _ in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8318/api/health >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:8318/api/health >/dev/null

echo "HTTP deployment is live at http://$PUBLIC_IP"
echo "Next: sudo bash $APP_DIR/butler/deploy/enable-ip-https.sh"
