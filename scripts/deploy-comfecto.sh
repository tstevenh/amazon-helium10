#!/usr/bin/env bash
#
# Deploy PPC OS to the comfecto server, which already runs nginx + n8n.
#
#   cd ~/ppc-os && bash scripts/deploy-comfecto.sh
#
# Written for THIS server specifically:
#   - Docker is already installed
#   - nginx owns 80/443 and fronts n8n, azpod, etsy-research and upload.comfecto
#   - ads.comfecto.com already has a working Let's Encrypt certificate
#   - port 8000 is taken by an unrelated uvicorn process
#
# So it does NOT install Docker, does NOT touch ports 80/443, and does NOT
# request a certificate. It runs the app on 127.0.0.1:3000 and points the
# existing nginx site at it.
#
# Safe to re-run. Never overwrites an existing .env, and never replaces the
# nginx config without backing it up and testing it first.
set -euo pipefail

DOMAIN="ads.comfecto.com"
NGINX_CONF="/etc/nginx/sites-enabled/${DOMAIN}.conf"
COMPOSE="sudo docker compose -f docker-compose.yml -f docker-compose.behind-nginx.yml"

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m !  %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m !! %s\033[0m\n' "$*" >&2; exit 1; }

[[ -f docker-compose.yml ]] || die "Run this from inside the ppc-os directory."
command -v docker >/dev/null || die "Docker not found — unexpected on this server."

# ── 1. Do not disturb what is already running ──────────────────────────────
say "Checking we will not collide with n8n"
if sudo ss -lntp 2>/dev/null | grep -q '127.0.0.1:3000 '; then
    sudo ss -lntp | grep '127.0.0.1:3000 ' || true
    die "Something already listens on 127.0.0.1:3000. Investigate before continuing."
fi
echo "  port 3000 free"
echo "  nginx and n8n untouched by this script"

# ── 2. Secrets ─────────────────────────────────────────────────────────────
if [[ -f .env ]]; then
    say ".env exists — keeping it"
    warn "Not regenerating secrets: a new FERNET_KEY would invalidate the"
    warn "stored Amazon token and force OAuth to be run again."
else
    say "Generating fresh secrets"
    ADMIN_PW="$(openssl rand -base64 24 | tr -d '/+=' | head -c 20)"
    FERNET="$(sudo docker run --rm python:3.12-slim sh -c \
        'pip install -q cryptography && python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"' 2>/dev/null | tail -1)"
    [[ -n "$FERNET" ]] || die "Could not generate FERNET_KEY."

    cat > .env <<ENVEOF
# Generated $(date -u +%Y-%m-%dT%H:%M:%SZ) by scripts/deploy-comfecto.sh
# Every secret below is new. Nothing was copied from a development machine.

POSTGRES_USER=ppc_os
POSTGRES_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
POSTGRES_DB=ppc_os

JWT_SECRET_KEY=$(openssl rand -base64 48 | tr -d '/+=' | head -c 48)
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=480

# Encrypts the stored Amazon refresh token. Changing it forces a reconnect.
FERNET_KEY=${FERNET}

# ── PASTE THESE TWO IN, THEN RE-RUN THIS SCRIPT ────────────────────────────
AMAZON_CLIENT_ID=PASTE_ME
AMAZON_CLIENT_SECRET=PASTE_ME

AMAZON_MOCK_MODE=false
# Goes through /backend because the API has no public port on this server —
# nginx forwards everything to Next.js, which proxies /backend to the API.
# Register this EXACT string in the Amazon LWA application.
AMAZON_REDIRECT_URI=https://${DOMAIN}/backend/accounts/oauth/callback
AMAZON_API_BASE_URL=https://advertising-api.amazon.com

# OFF. The app reads and suggests; it cannot change the ad account.
AMAZON_WRITE_ENABLED=false

SEED_ADMIN_EMAIL=admin@comfecto.com
SEED_ADMIN_PASSWORD=${ADMIN_PW}
SEED_USER_EMAIL=user@comfecto.com
SEED_USER_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 20)

# Set this to a Slack or Discord webhook so failures reach a human.
ALERT_WEBHOOK_URL=

FRONTEND_URL=https://${DOMAIN}
ENV=production
ENVEOF
    chmod 600 .env
    echo
    echo "  ┌───────────────────────────────────────────────┐"
    echo "  │  Admin login: admin@comfecto.com              │"
    printf  "  │  Password:    %-31s │\n" "$ADMIN_PW"
    echo "  └───────────────────────────────────────────────┘"
    echo
    warn "Write that down now."
fi

if grep -q PASTE_ME .env; then
    echo
    warn "Amazon credentials are still placeholders."
    echo
    echo "    nano .env          # fill in AMAZON_CLIENT_ID and AMAZON_CLIENT_SECRET"
    echo "    bash scripts/deploy-comfecto.sh"
    echo
    exit 1
fi

# ── 3. Build and start ─────────────────────────────────────────────────────
say "Building (a few minutes the first time)"
$COMPOSE build

say "Starting the stack"
$COMPOSE up -d

say "Waiting for Postgres"
for _ in $(seq 1 60); do
    $COMPOSE exec -T postgres pg_isready -U ppc_os >/dev/null 2>&1 && { echo "  ready"; break; }
    sleep 2
done

say "Applying migrations"
$COMPOSE exec -T api alembic upgrade head

say "Seeding users"
$COMPOSE exec -T api python -m app.modules.auth.seed || true

say "Waiting for the frontend"
for _ in $(seq 1 45); do
    curl -fsS -o /dev/null http://127.0.0.1:3000 2>/dev/null && { echo "  answering"; break; }
    sleep 2
done
curl -fsS -o /dev/null http://127.0.0.1:3000 2>/dev/null \
    || die "Frontend not answering on 127.0.0.1:3000. Check: $COMPOSE logs frontend"

# ── 4. nginx ───────────────────────────────────────────────────────────────
if grep -q "proxy_pass http://127.0.0.1:3000" "$NGINX_CONF" 2>/dev/null; then
    say "nginx already points at the app — leaving it alone"
else
    say "Pointing nginx at the app"
    BACKUP="$HOME/${DOMAIN}.conf.backup.$(date +%s)"
    sudo cp "$NGINX_CONF" "$BACKUP"
    echo "  backed up to $BACKUP"

    sudo tee "$NGINX_CONF" > /dev/null <<NGINXEOF
server {
    server_name ${DOMAIN};

    # Amazon syncs run 20-40 minutes and the app polls over the same
    # connection. nginx's 60s default would cut them off mid-request.
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
    client_max_body_size 64M;   # Cerebro CSV uploads

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_cache_bypass \$http_upgrade;
    }

    listen [::]:443 ssl ipv6only=on; # managed by Certbot
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}
server {
    if (\$host = ${DOMAIN}) {
        return 301 https://\$host\$request_uri;
    } # managed by Certbot

    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};
    return 404; # managed by Certbot
}
NGINXEOF

    # Tested BEFORE reloading: a bad config would take n8n down with it.
    if ! sudo nginx -t; then
        warn "nginx config invalid — restoring the backup and leaving nginx alone"
        sudo cp "$BACKUP" "$NGINX_CONF"
        die "nginx not reloaded. Nothing changed."
    fi
    sudo systemctl reload nginx
    echo "  nginx reloaded"
fi

# ── 5. Verify from outside ─────────────────────────────────────────────────
say "Checking https://${DOMAIN}"
sleep 3
CODE="$(curl -s -o /dev/null -w '%{http_code}' "https://${DOMAIN}" || echo 000)"
echo "  HTTP ${CODE}"

say "Reclaiming build cache"
sudo docker builder prune -af >/dev/null 2>&1 || true

cat <<DONE

────────────────────────────────────────────────────────────────────────
 Deployed:  https://${DOMAIN}

 n8n and the other sites were not touched.
 Writes to Amazon are OFF — the app can read and suggest, not change.

 Next:
   1. Register this redirect URI in the Amazon LWA app, exactly:
        https://${DOMAIN}/backend/accounts/oauth/callback
   2. Sign in, Settings -> Accounts, connect Amazon (OAuth must be re-run:
      this server has its own FERNET_KEY).
   3. Run Sync All. First sync takes 20-40 minutes per report.
   4. Put a webhook in ALERT_WEBHOOK_URL so failures reach someone.

 Logs:     $COMPOSE logs -f api
 Status:   $COMPOSE ps
 Rollback: sudo cp ~/${DOMAIN}.conf.backup.* ${NGINX_CONF} && sudo systemctl reload nginx
────────────────────────────────────────────────────────────────────────
DONE
