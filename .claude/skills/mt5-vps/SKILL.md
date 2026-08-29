---
name: mt5-vps
description: >
  Installer, démarrer, diagnostiquer et exploiter le bot grid scalper BTC de
  mt5-grid-bot/ sur un VPS Linux — chaîne Wine + Xvfb + terminal MetaTrader 5 +
  pont RPyC + services systemd. Utilise cette skill dès que la session tourne
  sur un VPS et que la demande touche à MetaTrader, MT5, Wine, au bot de
  trading, au pont RPyC, au compte démo, à un service gridbot-*, ou dès qu'on
  te demande de « lancer le bot », « voir où ça en est », « le bot ne trade
  pas », « il n'y a pas d'ordres », « installer MT5 sur le serveur » — y compris
  quand MetaTrader n'est pas nommé explicitement mais que le contexte est ce
  dépôt sur un serveur.
---

# Exploitation du grid scalper MT5 sur VPS

Tu pilotes de l'argent, même en démo, sur une machine que personne ne surveille.
Deux conséquences pratiques : ne démarre jamais le bot sur un état que tu n'as
pas vérifié, et préfère t'arrêter en expliquant ce qui bloque plutôt que de
contourner un garde-fou pour « que ça marche ».

## L'outil central : le diagnostic

`deploy/doctor.py` inspecte toute la chaîne et renvoie un verdict par élément
avec la commande de réparation. C'est ta source de vérité — plus fiable que de
déduire l'état du système à partir de messages d'erreur indirects.

```bash
cd /opt/grid-bot
python3 deploy/doctor.py --config config.json                # complet
python3 deploy/doctor.py --config config.json --skip-trading # sans interroger le broker
python3 deploy/doctor.py --config config.json --json         # sortie machine
```

Code de sortie 0 = chaîne exploitable, 1 = au moins un ÉCHEC.

Lance-le **au début de toute intervention** : il te dit où tu en es sans que tu
aies à explorer. Et relance-le **après chaque étape** d'installation plutôt que
de supposer que l'étape a réussi.

Ne réimplémente pas ces vérifications à la main. En particulier, n'utilise
jamais `pgrep -f Xvfb` ou `pgrep -f terminal64.exe` : la recherche plein texte
matche ta propre ligne de commande et te répond « présent » alors que rien ne
tourne. Le diagnostic lit `/proc/<pid>/comm`, qui ne ment pas.

## Les quatre règles qui ne se négocient pas

**Le pont RPyC n'écoute que sur 127.0.0.1.** C'est un serveur d'exécution de
code arbitraire sans authentification : exposé sur une IP publique, il donne un
shell à Internet. Si le diagnostic signale une écoute sur `0.0.0.0`, c'est une
urgence — arrête le service, corrige `--host` dans
`gridbot-mt5-bridge.service`, redémarre, `ufw deny 18812`.

**Compte de démonstration tant que l'utilisateur n'a pas explicitement demandé
le réel.** `require_demo_account: true` fait échouer le démarrage sur un compte
réel. Si ça bloque, ne passe pas le garde-fou à `false` : dis-le et demande.
Basculer un compte de trading en réel est une décision de l'utilisateur, jamais
une étape de dépannage.

**`martingale_factor` reste à 1.0.** Au-delà, la grille finit statistiquement à
zéro. Si tu le trouves supérieur, signale-le.

**Aucun démarrage du bot sur un diagnostic rouge.** Un service en échec ne se
« relance juste pour voir » : lis d'abord `journalctl -u <unité> -n 50`.

## Installation

`deploy/install-vps.sh` fait tout d'un bloc et convient quand la machine est
vierge. Mais tu peux aussi dérouler les étapes une à une, ce qui est préférable
quand la machine a déjà servi ou quand une étape a échoué : tu vérifies entre
chaque, et tu ne réinstalles pas ce qui est déjà là.

Ordre des dépendances, chaque étape validée par un diagnostic avant la suivante :

| # | Étape | Vérification |
|---|---|---|
| 1 | paquets : `wine wine64 wine32 winbind xvfb x11vnc python3-venv` | ligne `wine` du diagnostic |
| 2 | utilisateur `gridbot`, dossier `/opt/grid-bot` | `id gridbot` |
| 3 | service `gridbot-xvfb` | ligne `affichage virtuel` |
| 4 | préfixe Wine (`wineboot --init`) | `ls ~gridbot/.wine/drive_c` |
| 5 | terminal MT5 sous Wine | ligne `terminal MT5` |
| 6 | Python Windows + `MetaTrader5` + `rpyc` sous Wine | `wine python.exe -c "import MetaTrader5"` |
| 7 | venv Linux + `pip install -r requirements.txt` | `python3 -m unittest discover -s tests` |
| 8 | services systemd | lignes `service gridbot-*` |

Détail des commandes : `deploy/README.md` et `deploy/install-vps.sh`, qui sont
la référence. Ne recopie pas les commandes ici de mémoire, lis les fichiers.

Les étapes 5 et 6 sont les plus fragiles : les installeurs MT5 et Python sous
Wine échouent silencieusement selon la version de Wine. C'est pourquoi tu
vérifies après, au lieu de faire confiance au code de retour.

## Identifiants du compte

`mt5.initialize()` sait se connecter avec `login` / `password` / `server`, donc
la connexion au compte démo ne demande **pas** d'interface graphique — inutile
de monter un VNC pour ça.

Mais n'écris jamais un mot de passe de broker dans `config.json`. La
configuration accepte les variables d'environnement :

```json
"terminal": {
  "login": "${MT5_LOGIN}",
  "password": "${MT5_PASSWORD}",
  "server": "Broker-Demo",
  "bridge_host": "127.0.0.1"
}
```

Les variables se déclarent dans le service systemd via
`EnvironmentFile=/etc/gridbot.env` (fichier en `chmod 600`, propriétaire
`gridbot`). Une variable manquante fait échouer le chargement avec un message
explicite, plutôt que de laisser le broker rejeter une connexion pour une raison
incompréhensible.

Demande les identifiants à l'utilisateur, écris-les dans le fichier
d'environnement, et ne les répète jamais dans tes réponses ni dans un commit.

## Démarrage

Dans cet ordre, en vérifiant entre chaque — le pont ne sert à rien sans
terminal, et le bot ne sert à rien sans pont :

```bash
systemctl start gridbot-mt5-terminal && sleep 30
systemctl start gridbot-mt5-bridge   && sleep 10
python3 deploy/doctor.py --config config.json      # doit sortir en 0
systemctl enable --now gridbot-grid-bot
journalctl -u gridbot-grid-bot -f --lines 50
```

Deux ajustements que le diagnostic ne peut pas deviner et qu'il faut demander à
l'utilisateur : le **libellé exact du symbole BTC** chez son broker (`BTCUSD`,
`BTCUSD.a`, `Bitcoin`…) et son **spread réel**, pour calibrer `max_spread`.
Le diagnostic affiche le spread courant, ce qui aide à trancher.

## Lire les journaux

| Ligne | Sens |
|---|---|
| `Ancre initialisee a X` | la grille s'est posée, c'est le démarrage normal |
| `Palier B2 arme` | le broker a accepté un ordre limite |
| `Paliers liberes` | un take profit a été touché — un scalp encaissé |
| `Pas de grille : X -> Y` | l'ATR a bougé, la grille s'est adaptée |
| `bloque: spread ...` | spread au-dessus de la limite, aucun ordre posé |
| `ARRET RISQUE` | une limite a sauté, tout a été fermé |
| `rejet retcode=...` | le broker a refusé un ordre — la cause est dans le code |

## Diagnostic des symptômes courants

**« Le bot ne prend aucune position. »** Ce n'est presque jamais une panne.
Regarde dans l'ordre : `bloque: spread` dans les journaux (spread trop large),
`dry_run: true` (mode papier, aucun ordre réel), un `ARRET RISQUE` antérieur
(l'état est dans `state/grid_state.json`, et un arrêt terminal ne se lève qu'avec
`run.py reset`), ou simplement le marché qui n'a pas atteint un palier — avec la
configuration livrée, les pas font 200 $ et plus, donc quelques heures sans
exécution sont normales.

**Le terminal se fait tuer au bout de quelques heures.** OOM killer :
`dmesg | grep -i oom`. MT5 sous Wine demande ~2 Go. Ajoute du swap.

**Le pont ne répond plus après un redémarrage du terminal.** Le pont dépend du
terminal mais ne détecte pas sa reconnexion : `systemctl restart
gridbot-mt5-bridge`.

**`ECHEC connexion au compte`.** Vérifie dans cet ordre : les variables
d'environnement du service (`systemctl show gridbot-grid-bot -p Environment`),
le nom exact du serveur broker (sensible à la casse), puis que le terminal est
bien connecté.

## Modifier la stratégie

Les paramètres livrés sont le produit d'environ 12 000 backtests, documentés
dans `README.md` (section « Ce que la recherche de paramètres a montré »). Lis-la
avant de changer un paramètre : plusieurs intuitions raisonnables y sont
mesurées et réfutées — le stop temporel, le filtre de tendance, et resserrer le
budget de drawdown dégradent tous le résultat.

Pour tester une variante, ne la mets pas en production : compare-la d'abord.

```bash
python3 validate.py config.json /tmp/variante.json --seeds 201-216 --bars 20000
```

Change un seul paramètre à la fois, et juge sur le **taux de ruine** et la
**médiane**, pas sur le rendement moyen — une grille a des moyennes flatteuses
tirées par quelques marchés en range pendant que le run typique perd.

## Arrêt et urgence

```bash
# fermer positions et ordres immédiatement, puis arrêter
python3 run.py -c config.json flatten
systemctl stop gridbot-grid-bot

# arrêt propre sans fermer les positions (elles gardent leurs TP chez le broker)
systemctl stop gridbot-grid-bot

# lever un arrêt de risque terminal, après avoir compris pourquoi il s'est déclenché
python3 run.py -c config.json reset
```

`flatten` agit toujours sur le compte réellement connecté, y compris quand
`dry_run` est actif — c'est le bouton d'arrêt d'urgence, il ne simule pas.

Avant un `reset`, cherche la cause dans les journaux et dis-la à l'utilisateur.
Un arrêt terminal signifie que la stratégie a perdu son budget de risque ; le
relancer sans rien comprendre revient à le reperdre.
