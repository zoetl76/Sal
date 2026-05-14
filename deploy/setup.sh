#!/bin/bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  SAL Market — Script d'installation VPS Ubuntu 22/24        ║
# ║  Usage: bash setup.sh TON_DOMAINE.COM                        ║
# ╚══════════════════════════════════════════════════════════════╝
set -e

DOMAIN="${1:-sal.example.com}"
APP_DIR="/opt/sal"
USER="sal"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

[ "$EUID" -ne 0 ] && error "Lance ce script en root: sudo bash setup.sh $DOMAIN"
[ -z "$1" ] && error "Usage: sudo bash setup.sh TON_DOMAINE.COM"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Installation SAL Market sur $DOMAIN"
echo "╚══════════════════════════════════════════╝"
echo ""

# ──────────────────────────────────────────────
#  1. Paquets système
# ──────────────────────────────────────────────
info "Mise à jour du système..."
apt-get update -qq && apt-get upgrade -y -qq

info "Installation des dépendances système..."
apt-get install -y -qq \
  curl git nginx certbot python3-certbot-nginx \
  python3 python3-pip python3-venv \
  nodejs npm build-essential

# Node.js 20 LTS
if ! node -v | grep -q "v20"; then
  info "Installation Node.js 20..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

# PM2 (gestionnaire de processus)
npm install -g pm2 --quiet

info "Versions: $(node -v) / $(npm -v) / $(python3 -V)"

# ──────────────────────────────────────────────
#  2. Utilisateur système dédié
# ──────────────────────────────────────────────
if ! id "$USER" &>/dev/null; then
  useradd -m -s /bin/bash "$USER"
  info "Utilisateur '$USER' créé."
fi

# ──────────────────────────────────────────────
#  3. Cloner le dépôt
# ──────────────────────────────────────────────
info "Clonage du dépôt..."
mkdir -p "$APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull
else
  git clone https://github.com/zoetl76/Sal.git "$APP_DIR"
fi
chown -R "$USER:$USER" "$APP_DIR"

# ──────────────────────────────────────────────
#  4. Python venv + dépendances bot/oracle
# ──────────────────────────────────────────────
info "Environnement Python..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/bot/requirements.txt"

# ──────────────────────────────────────────────
#  5. Frontend React → build statique
# ──────────────────────────────────────────────
info "Build du frontend React..."
cd "$APP_DIR/frontend"
sudo -u "$USER" npm install --silent
# Les variables d'env seront injectées depuis .env
if [ -f "$APP_DIR/.env" ]; then
  export $(grep -v '^#' "$APP_DIR/.env" | grep 'VITE_' | xargs)
fi
sudo -u "$USER" npm run build

# ──────────────────────────────────────────────
#  6. Nginx
# ──────────────────────────────────────────────
info "Configuration Nginx pour $DOMAIN..."
cat > "/etc/nginx/sites-available/sal" <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    # Frontend React (build statique)
    location / {
        root $APP_DIR/frontend/dist;
        try_files \$uri \$uri/ /index.html;
        add_header X-Frame-Options "ALLOWALL";
        add_header Content-Security-Policy "frame-ancestors *";
    }

    # Oracle API + WebSocket
    location /api/ {
        proxy_pass         http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host \$host;
        proxy_read_timeout 300;
    }

    location /ws/ {
        proxy_pass         http://127.0.0.1:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_read_timeout 3600;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/sal /etc/nginx/sites-enabled/sal
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ──────────────────────────────────────────────
#  7. SSL avec Let's Encrypt
# ──────────────────────────────────────────────
info "Certificat SSL Let's Encrypt pour $DOMAIN..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
  --email "admin@$DOMAIN" --redirect
info "HTTPS activé ✓"

# ──────────────────────────────────────────────
#  8. Services PM2 (oracle + bot)
# ──────────────────────────────────────────────
info "Création des services PM2..."
PYTHON="$APP_DIR/.venv/bin/python"

# Arrêter les anciens processus si existants
sudo -u "$USER" pm2 delete sal-oracle 2>/dev/null || true
sudo -u "$USER" pm2 delete sal-bot    2>/dev/null || true

sudo -u "$USER" pm2 start "$PYTHON" \
  --name "sal-oracle" \
  --cwd "$APP_DIR/bot" \
  -- oracle.py

sudo -u "$USER" pm2 start "$PYTHON" \
  --name "sal-bot" \
  --cwd "$APP_DIR/bot" \
  -- bot.py

sudo -u "$USER" pm2 save
pm2 startup systemd -u "$USER" --hp "/home/$USER" | tail -1 | bash

# ──────────────────────────────────────────────
#  9. Résumé
# ──────────────────────────────────────────────
echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║  ✅  SAL Market déployé avec succès !              ║"
echo "╠════════════════════════════════════════════════════╣"
echo "║  🌐 Frontend : https://$DOMAIN"
echo "║  📡 Oracle   : https://$DOMAIN/api/price"
echo "║  🔌 WebSocket: wss://$DOMAIN/ws/price"
echo "╠════════════════════════════════════════════════════╣"
echo "║  Prochaines étapes:                                ║"
echo "║  1. Editer /opt/sal/.env (voir section config)     ║"
echo "║  2. pm2 restart all                                ║"
echo "║  3. Dans BotFather: /setmenubutton                 ║"
echo "║     → https://$DOMAIN                             ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""
warn "Configure /opt/sal/.env puis relance: pm2 restart all"
