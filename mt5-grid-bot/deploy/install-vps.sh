#!/bin/bash
# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Grid Scalper BTC — installation sur VPS Ubuntu 22.04 / 24.04        ║
# ║  Usage : sudo bash install-vps.sh                                    ║
# ║                                                                      ║
# ║  Installe Wine, un affichage virtuel, le terminal MetaTrader 5,      ║
# ║  un Python Windows avec l'API MT5, et le bot cote Linux.            ║
# ╚══════════════════════════════════════════════════════════════════════╝
set -euo pipefail

APP_USER="${APP_USER:-gridbot}"
APP_DIR="${APP_DIR:-/opt/grid-bot}"
WINEPREFIX_DIR="/home/${APP_USER}/.wine"
DISPLAY_NUM="${DISPLAY_NUM:-:99}"
BRIDGE_PORT="${BRIDGE_PORT:-18812}"
PY_WIN_VERSION="${PY_WIN_VERSION:-3.11.9}"
REPO_URL="${REPO_URL:-}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }
step()  { echo -e "\n${BLUE}[$1]${NC} $2"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

[ "$EUID" -ne 0 ] && error "Lance ce script en root : sudo bash install-vps.sh"

. /etc/os-release 2>/dev/null || error "Distribution non identifiable"
[[ "$VERSION_ID" == "22.04" || "$VERSION_ID" == "24.04" ]] || \
  warn "Teste sur Ubuntu 22.04 et 24.04 ; ici $PRETTY_NAME. Ca peut marcher quand meme."

MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
[ "$MEM_MB" -lt 1800 ] && warn "Seulement ${MEM_MB} Mo de RAM. MT5 sous Wine en demande ~2 Go ; prevois du swap."

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║  Grid Scalper BTC — installation VPS               ║"
echo "╚════════════════════════════════════════════════════╝"
echo "  utilisateur : $APP_USER"
echo "  dossier     : $APP_DIR"
echo "  affichage   : $DISPLAY_NUM"
echo "  pont RPyC   : 127.0.0.1:$BRIDGE_PORT (jamais expose publiquement)"
echo ""

# ─────────────────────────────────────────────────────────────────────
step "1/8" "Paquets systeme"
dpkg --add-architecture i386
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  wine wine64 wine32 winbind cabextract \
  xvfb x11vnc xdotool \
  python3 python3-venv python3-pip \
  git curl unzip ca-certificates >/dev/null
info "Wine $(wine --version 2>/dev/null || echo '?') installe"

# ─────────────────────────────────────────────────────────────────────
step "2/8" "Utilisateur applicatif"
if id "$APP_USER" &>/dev/null; then
  info "L'utilisateur $APP_USER existe deja"
else
  useradd --create-home --shell /bin/bash "$APP_USER"
  info "Utilisateur $APP_USER cree"
fi
mkdir -p "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

run_as() { sudo -u "$APP_USER" env HOME="/home/$APP_USER" WINEPREFIX="$WINEPREFIX_DIR" \
             WINEDEBUG=-all DISPLAY="$DISPLAY_NUM" "$@"; }

# ─────────────────────────────────────────────────────────────────────
step "3/8" "Affichage virtuel (le terminal MT5 a besoin d'un serveur X)"
install -m 644 /dev/stdin /etc/systemd/system/gridbot-xvfb.service <<EOF
[Unit]
Description=Affichage virtuel X pour MetaTrader 5
After=network.target

[Service]
User=$APP_USER
ExecStart=/usr/bin/Xvfb $DISPLAY_NUM -screen 0 1280x1024x24 -nolisten tcp
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now gridbot-xvfb.service
sleep 2
info "Xvfb actif sur $DISPLAY_NUM"

# ─────────────────────────────────────────────────────────────────────
step "4/8" "Prefixe Wine"
if [ -d "$WINEPREFIX_DIR" ]; then
  info "Prefixe Wine deja initialise"
else
  run_as wineboot --init >/dev/null 2>&1 || true
  sleep 5
  info "Prefixe Wine initialise dans $WINEPREFIX_DIR"
fi

# ─────────────────────────────────────────────────────────────────────
step "5/8" "Terminal MetaTrader 5"
MT5_EXE="$WINEPREFIX_DIR/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ -f "$MT5_EXE" ]; then
  info "MetaTrader 5 deja installe"
else
  sudo -u "$APP_USER" curl -fsSL -o "/tmp/mt5setup.exe" \
    "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe" \
    || error "Telechargement de MT5 impossible (verifie la sortie reseau du VPS)"
  warn "Installation de MT5 : silencieuse, compte ~2 minutes."
  run_as wine /tmp/mt5setup.exe /auto >/dev/null 2>&1 || true
  sleep 20
  [ -f "$MT5_EXE" ] || warn "terminal64.exe introuvable — termine l'installation via VNC (etape finale)."
  info "MetaTrader 5 installe"
fi

# ─────────────────────────────────────────────────────────────────────
step "6/8" "Python Windows + API MetaTrader5 + RPyC (sous Wine)"
PY_WIN="$WINEPREFIX_DIR/drive_c/Python311/python.exe"
if [ -f "$PY_WIN" ]; then
  info "Python Windows deja installe"
else
  sudo -u "$APP_USER" curl -fsSL -o "/tmp/python-win.exe" \
    "https://www.python.org/ftp/python/${PY_WIN_VERSION}/python-${PY_WIN_VERSION}-amd64.exe" \
    || error "Telechargement de Python Windows impossible"
  run_as wine /tmp/python-win.exe /quiet InstallAllUsers=1 TargetDir='C:\Python311' \
    PrependPath=1 Include_test=0 >/dev/null 2>&1 || true
  sleep 25
  [ -f "$PY_WIN" ] || error "Python Windows non installe. Relance l'etape 6 manuellement."
  info "Python Windows $PY_WIN_VERSION installe"
fi
run_as wine "$PY_WIN" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
run_as wine "$PY_WIN" -m pip install --quiet MetaTrader5 rpyc >/dev/null 2>&1 \
  || error "Installation de MetaTrader5/rpyc sous Wine impossible"
info "MetaTrader5 + rpyc installes cote Wine"

# ─────────────────────────────────────────────────────────────────────
step "7/8" "Bot cote Linux"
if [ -n "$REPO_URL" ] && [ ! -d "$APP_DIR/.git" ]; then
  sudo -u "$APP_USER" git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi
[ -f "$APP_DIR/run.py" ] || error "run.py introuvable dans $APP_DIR. Copie le dossier mt5-grid-bot ici, ou passe REPO_URL=..."

sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt" \
  || error "Installation des dependances Python impossible"

if [ ! -f "$APP_DIR/config.json" ]; then
  sudo -u "$APP_USER" cp "$APP_DIR/config.demo.json" "$APP_DIR/config.json"
  sudo -u "$APP_USER" python3 - "$APP_DIR/config.json" "$BRIDGE_PORT" <<'PY'
import json, sys
path, port = sys.argv[1], int(sys.argv[2])
cfg = json.load(open(path))
cfg["terminal"]["bridge_host"] = "127.0.0.1"
cfg["terminal"]["bridge_port"] = port
json.dump(cfg, open(path, "w"), indent=2, ensure_ascii=False)
PY
  info "config.json cree depuis config.demo.json (compte de demonstration, pont active)"
fi
info "Bot installe dans $APP_DIR"

# ─────────────────────────────────────────────────────────────────────
step "8/8" "Services systemd"
for unit in mt5-terminal mt5-bridge grid-bot; do
  sed -e "s|@APP_USER@|$APP_USER|g" -e "s|@APP_DIR@|$APP_DIR|g" \
      -e "s|@WINEPREFIX@|$WINEPREFIX_DIR|g" -e "s|@DISPLAY@|$DISPLAY_NUM|g" \
      -e "s|@BRIDGE_PORT@|$BRIDGE_PORT|g" -e "s|@PY_WIN@|C:\\\\Python311\\\\python.exe|g" \
      "$(dirname "$0")/systemd/${unit}.service" > "/etc/systemd/system/gridbot-${unit}.service"
done
systemctl daemon-reload
systemctl enable gridbot-mt5-terminal.service gridbot-mt5-bridge.service >/dev/null
info "Services installes (le bot n'est PAS demarre automatiquement, c'est voulu)"

# ─────────────────────────────────────────────────────────────────────
cat <<EOF

╔════════════════════════════════════════════════════════════════════╗
║  Installation terminee — il reste 3 choses a faire a la main      ║
╚════════════════════════════════════════════════════════════════════╝

1. CONNECTER LE TERMINAL A TON COMPTE DEMO
   Le terminal tourne sans ecran : ouvre-le en VNC depuis ta machine.

     # sur le VPS
     sudo -u $APP_USER DISPLAY=$DISPLAY_NUM x11vnc -localhost -nopw -forever &
     # sur ta machine
     ssh -L 5900:localhost:5900 root@<ip-du-vps>
     # puis connecte un client VNC sur localhost:5900

   Dans MT5 : Fichier > Se connecter a un compte de trading (compte DEMO),
   puis Outils > Options > Expert Advisors > Autoriser le trading algorithmique.
   Note le libelle exact du symbole BTC dans l'Observation du marche.

2. AJUSTER LA CONFIGURATION
     nano $APP_DIR/config.json
   - "symbol" : le libelle exact releve a l'etape 1
   - "risk": {"max_spread"} : le spread reel observe sur BTC chez ce broker

3. DEMARRER, DANS CET ORDRE
     systemctl start gridbot-mt5-terminal
     systemctl start gridbot-mt5-bridge
     sudo -u $APP_USER $APP_DIR/.venv/bin/python $APP_DIR/run.py -c $APP_DIR/config.json status
     # si le statut est bon :
     systemctl enable --now gridbot-grid-bot

   Journaux :   journalctl -u gridbot-grid-bot -f
   Arret net :  sudo -u $APP_USER $APP_DIR/.venv/bin/python $APP_DIR/run.py -c $APP_DIR/config.json flatten

SECURITE — le pont RPyC execute du code arbitraire a distance par conception.
Il ecoute sur 127.0.0.1 uniquement. Ne l'expose JAMAIS sur l'exterieur :
  ufw deny $BRIDGE_PORT
Verifie apres demarrage :  ss -tlnp | grep $BRIDGE_PORT   ->  doit afficher 127.0.0.1

EOF
info "Termine."
