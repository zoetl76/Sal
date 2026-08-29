#!/bin/bash
# Mise a jour du bot sans toucher a Wine ni au terminal.
set -euo pipefail
APP_USER="${APP_USER:-gridbot}"
APP_DIR="${APP_DIR:-/opt/grid-bot}"

echo "[1/4] Arret du bot (les positions ouvertes restent ouvertes)..."
systemctl stop gridbot-grid-bot || true

echo "[2/4] Recuperation du code..."
sudo -u "$APP_USER" git -C "$APP_DIR" pull

echo "[3/4] Dependances..."
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "[4/4] Tests avant redemarrage..."
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -m unittest discover -s "$APP_DIR/tests" -q \
  || { echo "Tests en echec : le bot n'est PAS redemarre."; exit 1; }

systemctl start gridbot-grid-bot
echo "Mise a jour terminee. Journaux : journalctl -u gridbot-grid-bot -f"
