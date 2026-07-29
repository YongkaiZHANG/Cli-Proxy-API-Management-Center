#!/usr/bin/env bash
set -euo pipefail

PUBLIC_IP="${PUBLIC_IP:-112.74.109.99}"
APP_DIR="${APP_DIR:-/opt/cli-proxy-management}"
CERTBOT_VENV="${CERTBOT_VENV:-/opt/certbot}"
EMAIL="${LETSENCRYPT_EMAIL:-}"

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo -E bash $APP_DIR/butler/deploy/enable-ip-https.sh" >&2
  exit 1
fi

apt-get update
apt-get install -y python3-venv python3-pip ca-certificates
python3 -m venv "$CERTBOT_VENV"
"$CERTBOT_VENV/bin/pip" install --upgrade pip 'certbot>=5.4'
ln -sfn "$CERTBOT_VENV/bin/certbot" /usr/local/bin/certbot

EMAIL_ARGS=(--register-unsafely-without-email)
if [[ -n "$EMAIL" ]]; then
  EMAIL_ARGS=(--email "$EMAIL" --no-eff-email)
fi

certbot certonly \
  --non-interactive \
  --agree-tos \
  "${EMAIL_ARGS[@]}" \
  --preferred-profile shortlived \
  --webroot \
  --webroot-path /var/www/letsencrypt \
  --ip-address "$PUBLIC_IP"

install -m 0644 "$APP_DIR/butler/deploy/nginx-https.conf" /etc/nginx/sites-available/butler
sed -i "s|__PUBLIC_IP__|$PUBLIC_IP|g" /etc/nginx/sites-available/butler
nginx -t
systemctl reload nginx

install -m 0644 "$APP_DIR/butler/deploy/certbot-ip-renew.service" /etc/systemd/system/certbot-ip-renew.service
install -m 0644 "$APP_DIR/butler/deploy/certbot-ip-renew.timer" /etc/systemd/system/certbot-ip-renew.timer
systemctl daemon-reload
systemctl enable --now certbot-ip-renew.timer

curl -kfsS "https://127.0.0.1/api/health" -H "Host: $PUBLIC_IP" >/dev/null || true

echo "HTTPS enabled: https://$PUBLIC_IP"
echo "Certificate renewal timer: certbot-ip-renew.timer"
