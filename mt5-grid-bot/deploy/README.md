# Déploiement sur VPS

## Réponse courte

Cloner le repo sur le VPS ne suffit pas. Le repo, c'est le bot ; il lui faut un
terminal MetaTrader 5 en face, et sur un VPS Linux nu il n'y en a pas. Il manque
Wine, un serveur X (le terminal refuse de démarrer sans affichage), le terminal
lui-même connecté à ton compte, et — pour le bot Python — un Python Windows sous
Wine qui expose l'API via RPyC.

`install-vps.sh` fait tout ça.

## Deux chemins, choisis en connaissance de cause

| | EA MQL5 | Bot Python |
|---|---|---|
| Ce qui tourne | Wine + MT5 + l'EA | Wine + MT5 + Python Windows + RPyC + Python Linux + le bot |
| Pièces qui peuvent casser | 2 | 6 |
| Backtest | testeur MT5 (modélise spread et exécution) | `backtest.py` |
| Mode papier | non | oui |
| Surface d'attaque réseau | aucune | un serveur RPyC local |

**Sur un VPS, l'EA est le choix par défaut.** Copier
`mql5/GridScalperBTC.mq5` dans `~/.wine/drive_c/Program Files/MetaTrader 5/MQL5/Experts/`,
compiler dans MetaEditor, glisser sur un graphique BTCUSD : c'est fini. Pas de
Python, pas de pont, pas de service supplémentaire.

Prends le bot Python si tu veux le mode papier, les backtests hors terminal,
l'optimiseur, ou les journaux exploitables ailleurs.

## Si tu passes par une session Claude sur le VPS

C'est le chemin recommandé : la skill `mt5-vps` du dépôt (`.claude/skills/`)
contient le runbook complet, et `deploy/doctor.py` donne à la session un état
vérifiable du système plutôt qu'une déduction à partir de messages d'erreur.

```bash
cd /opt/grid-bot
python3 deploy/doctor.py --config config.json
```

Le diagnostic vérifie la mémoire, Wine, l'affichage virtuel, le terminal, le
port du pont **et sur quelle interface il écoute**, le type de compte
(démo/réel), le trading autorisé, le symbole, le spread courant, la
configuration et les services. Chaque échec vient avec sa commande de
réparation ; le code de sortie vaut 1 tant qu'il en reste un.

Lance-le avant de démarrer le bot, et après chaque étape d'installation.

## Installation manuelle

```bash
ssh root@<ip-du-vps>
git clone <ce-dépôt> /opt/grid-bot-src
sudo bash /opt/grid-bot-src/mt5-grid-bot/deploy/install-vps.sh
```

Ou en laissant le script cloner :

```bash
sudo REPO_URL=https://github.com/<toi>/<repo>.git bash install-vps.sh
```

Variables reconnues : `APP_USER` (défaut `gridbot`), `APP_DIR` (`/opt/grid-bot`),
`DISPLAY_NUM` (`:99`), `BRIDGE_PORT` (`18812`), `PY_WIN_VERSION` (`3.11.9`).

Le script installe cinq choses, dans cet ordre : les paquets système (Wine,
Xvfb, VNC), l'utilisateur applicatif, l'affichage virtuel, le terminal MT5, un
Python Windows avec `MetaTrader5` et `rpyc`, puis le bot dans son venv. Il
enregistre trois services systemd et **ne démarre pas le bot** : il reste
toujours trois choses à faire à la main, qu'il rappelle en fin d'exécution.

## Ce que le script ne peut pas faire pour toi

1. **Connecter le terminal à ton compte démo.** Ça demande de voir l'écran :

   ```bash
   # VPS
   sudo -u gridbot DISPLAY=:99 x11vnc -localhost -nopw -forever &
   # ta machine
   ssh -L 5900:localhost:5900 root@<ip-du-vps>
   # puis un client VNC sur localhost:5900
   ```

   Dans MT5 : connexion au compte **démo**, puis Outils → Options →
   Expert Advisors → **Autoriser le trading algorithmique**.

2. **Relever le libellé exact du symbole BTC** dans l'Observation du marché
   (`BTCUSD`, `BTCUSD.a`, `Bitcoin`…) et le mettre dans `config.json`.

3. **Calibrer `max_spread`** sur le spread réel de ton broker.

## Diagnostic

```bash
python3 deploy/doctor.py --config config.json                # complet
python3 deploy/doctor.py --config config.json --skip-trading # sans le broker
python3 deploy/doctor.py --config config.json --json         # sortie machine
```

## Identifiants

N'écris pas le mot de passe du broker dans `config.json`. La configuration
développe les variables d'environnement :

```json
"terminal": { "login": "${MT5_LOGIN}", "password": "${MT5_PASSWORD}",
              "server": "Broker-Demo", "bridge_host": "127.0.0.1" }
```

```bash
printf 'MT5_LOGIN=5031234\nMT5_PASSWORD=xxxx\n' > /etc/gridbot.env
chmod 600 /etc/gridbot.env && chown gridbot /etc/gridbot.env
```

Le service `gridbot-grid-bot` lit ce fichier. Une variable manquante fait
échouer le démarrage avec un message qui la nomme, plutôt que de laisser le
broker rejeter la connexion sans explication.

## Services

```
gridbot-xvfb          affichage virtuel
gridbot-mt5-terminal  terminal MT5 sous Wine
gridbot-mt5-bridge    serveur RPyC (dépend du terminal)
gridbot-grid-bot      le bot (dépend du pont)
```

Démarrage manuel du premier coup, dans l'ordre, en vérifiant `status` avant de
lancer le bot :

```bash
systemctl start gridbot-mt5-terminal
systemctl start gridbot-mt5-bridge
sudo -u gridbot /opt/grid-bot/.venv/bin/python /opt/grid-bot/run.py \
     -c /opt/grid-bot/config.json status
systemctl enable --now gridbot-grid-bot
```

Journaux : `journalctl -u gridbot-grid-bot -f`
Arrêt d'urgence : `run.py -c config.json flatten`

## Sécurité — le point à ne pas rater

Le pont est un **serveur RPyC « classic »**. Par conception, il exécute du code
Python arbitraire pour quiconque s'y connecte : c'est une exécution de code à
distance, sans authentification. Sur un VPS avec une IP publique, l'exposer
revient à donner un shell root à Internet.

Le service systemd force `--host 127.0.0.1`. Ne change pas cette valeur.
Vérifie après démarrage :

```bash
ss -tlnp | grep 18812      # doit afficher 127.0.0.1:18812, jamais 0.0.0.0
ufw deny 18812
```

Autres réflexes VPS : clé SSH plutôt que mot de passe, `ufw` en deny par défaut
sauf SSH, et le compte MT5 **démo** tant que la stratégie n'a pas fait ses
preuves chez toi — `config.demo.json` refuse de démarrer sur un compte réel.

## Dimensionnement

MT5 sous Wine tient dans ~2 Go de RAM avec l'affichage virtuel. En dessous, le
terminal se fait tuer par l'OOM killer au bout de quelques heures — ajoute du
swap ou prends plus gros. Le bot lui-même est négligeable (une boucle toutes les
2 s, aucun calcul lourd).

Coupure réseau ou redémarrage du VPS : les services redémarrent seuls dans le
bon ordre, et le bot recharge son état (ancre, pic d'equity, arrêts en cours)
depuis `state/grid_state.json`. Les positions ouvertes, elles, restent chez le
broker — c'est lui qui tient les TP, pas le bot.

## Ces scripts n'ont pas été exécutés sur un vrai VPS

Ils ont été écrits et relus, leur syntaxe shell est vérifiée, mais
l'environnement où ce dépôt a été développé n'a ni Wine ni accès réseau sortant
vers les dépôts APT et les serveurs de brokers. Lance-les sur une machine
jetable avant ta vraie, et attends-toi à ajuster les étapes 5 et 6 (les
installateurs MT5 et Python sous Wine sont capricieux et changent de
comportement d'une version de Wine à l'autre). Les services systemd et la
configuration, eux, sont indépendants de ces aléas.
