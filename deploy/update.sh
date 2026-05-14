#!/bin/bash
# Mise à jour rapide sans tout réinstaller
set -e
APP_DIR="/opt/sal"

echo "[1/3] Git pull..."
git -C "$APP_DIR" pull

echo "[2/3] Rebuild frontend..."
cd "$APP_DIR/frontend"
npm install --silent
npm run build

echo "[3/3] Redémarrage des services..."
pm2 restart sal-oracle sal-bot

echo "✅ Mise à jour terminée."
