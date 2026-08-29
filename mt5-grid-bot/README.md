# Grid Scalper BTC — MetaTrader 5

Bot de scalping en grille sur **BTCUSD**, livré en deux implémentations qui partagent
la même logique :

| | Fichier | Quand l'utiliser |
|---|---|---|
| **Bot Python** | `run.py` + `grid_bot/` | pilotage du terminal via l'API `MetaTrader5` (Windows, ou Linux via Wine et un pont RPyC), mode papier, backtest, journalisation, tests |
| **EA MQL5** | `mql5/GridScalperBTC.mq5` | exécution native dans MT5, testeur de stratégie intégré, VPS MetaQuotes |

---

## Avertissement, en une fois et sans détour

Une grille **n'a pas de stop loss par construction**. Elle gagne un peu, très
souvent, dans un marché qui oscille — et rend tout d'un coup dans une tendance
soutenue.

Les paramètres livrés ici sont le produit d'environ **12 000 backtests** (voir
« Ce que la recherche de paramètres a montré » plus bas). Voici ce qu'ils
donnent sur le jeu de validation final — 16 marchés simulés jamais utilisés
pour choisir quoi que ce soit, 6 régimes, ~70 jours chacun, compte de 2 000 $,
lot 0,01 :

| | Résultat |
|---|---|
| Rendement moyen | **+3,74 %** |
| Rendement médian | +0,70 % |
| Runs gagnants | 51 % |
| Pire run | −15,1 % (le stop de drawdown) |
| **Runs terminés par le stop de drawdown** | **36,5 %** |

Lis la dernière ligne deux fois. **Plus d'un marché sur trois se termine par
l'arrêt d'urgence à −15 %.** Ce n'est pas un défaut de réglage : c'est la
meilleure configuration trouvée après une recherche systématique, et rien de ce
qui a été testé ne fait disparaître ce chiffre.

Ce bot est conçu pour que la perte soit **bornée et choisie**
(`max_drawdown_pct`), pas pour être rentable par défaut.

## Comment ça marche

```
                              ┌──── S3  ancre + 3·pas   sell limit
                              ├──── S2  ancre + 2·pas   sell limit
                              ├──── S1  ancre + 1·pas   sell limit
   ancre  ────────────────────┤        (prix au démarrage de la grille)
                              ├──── B1  ancre − 1·pas   buy limit
                              ├──── B2  ancre − 2·pas   buy limit
                              └──── B3  ancre − 3·pas   buy limit
```

1. **Ancre** — au démarrage, le prix médian devient le centre de la grille.
2. **Pas** — soit fixe, soit `ATR(M15) × atr_mult` borné par `step_min`/`step_max`.
   Sur BTC, l'ATR change du simple au triple selon la période : le pas adaptatif
   évite d'avoir une grille absurdement serrée en pleine volatilité.
3. **Armement** — chaque palier libre reçoit un ordre limite, avec un take profit
   à exactement **un pas** de son prix d'entrée.
4. **Scalp** — le prix redescend d'un pas, `B1` se remplit ; il remonte d'un pas,
   `B1` prend son profit. Le palier se libère, attend `rearm_cooldown_sec`, se réarme.
5. **Re-centrage** — si le prix sort de la grille (`> pas × paliers × reanchor_mult`)
   *et* qu'aucune position n'est ouverte, la grille est déplacée sur le prix courant.
   Avec des positions ouvertes elle reste en place, sauf si `trail_grid` est activé.
6. **Recalage** — quand l'ATR fait bouger le pas, les ordres en attente désormais mal
   placés sont annulés et reposés au bon prix.

Chaque ordre porte un commentaire `GSB1`, `GSS2`… qui identifie son palier. Si le
broker tronque les commentaires, le palier est retrouvé par proximité de prix
(tolérance : 40 % du pas), donc jamais réarmé en double.

---

## Installation (bot Python)

### Windows

```bash
git clone <ce-dépôt>
cd mt5-grid-bot
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy config.example.json config.json
```

### Linux

MetaTrader 5 tourne très bien sous Linux, via Wine. Le seul point de friction
est le paquet Python : MetaQuotes ne publie que des wheels `win_amd64` (vérifié
sur PyPI — les neuf fichiers de la dernière version sont tous `win_amd64`). La
solution standard est un pont : un Python *Windows* tourne sous Wine à côté du
terminal et expose l'API via un serveur RPyC ; côté Linux, `pymt5linux`
(Python ≥ 3.13) ou `mt5linux` s'y connecte et fournit **exactement les mêmes
méthodes et les mêmes constantes**. Le bot les accepte sans modification.

```bash
# 1. Terminal MT5 sous Wine (script officiel MetaQuotes, ou installation manuelle)
sudo apt install wine64
wget https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe
wine mt5setup.exe

# 2. Python Windows + MetaTrader5 + serveur RPyC, sous le même préfixe Wine
wine python-3.11.x-amd64.exe        # depuis python.org
wine python -m pip install MetaTrader5 rpyc

# 3. Côté Linux : le bot et le client du pont
pip install -r requirements.txt
```

Lancer le serveur côté Wine, puis renseigner dans la configuration :

```json
"terminal": { "bridge_host": "127.0.0.1", "bridge_port": 18812 }
```

`bridge_host` vide (le défaut) signifie « paquet natif » : c'est le
comportement sous Windows. Dès qu'il est renseigné, le bot passe par le pont.
Si le pont n'est pas installé ou que le serveur ne répond pas, le message
d'erreur nomme l'hôte, le port et ce qu'il faut vérifier.

### Dans les deux cas

Dans le terminal MT5 : **Outils → Options → Expert Advisors → Autoriser le
trading algorithmique**. Vérifie aussi le libellé exact du symbole dans
l'Observation du marché : selon le broker c'est `BTCUSD`, `BTCUSD.a`,
`BTCUSD_raw`, `Bitcoin`… et il faut le reporter dans `config.json`.

## Démarrage

```bash
python run.py --config config.json               # mode papier (défaut)
python run.py --config config.json status        # état du compte et de la grille
python run.py --config config.json flatten       # arrêt d'urgence : tout fermer
python run.py --config config.json reset         # lève un arrêt de risque
python run.py --config config.json --live        # trading réel (demande une confirmation)
```

Le **mode papier** utilise les cotations réelles du broker mais n'envoie aucun
ordre : les exécutions, les TP et le PnL sont simulés en mémoire. C'est le mode
par défaut, et l'étape à ne pas sauter.

---

## Lancer en démo

Le compte de démonstration est l'étape obligatoire entre le mode papier et le
réel : mêmes serveurs, mêmes spreads, mêmes rejets d'ordres, argent fictif.

```bash
python run.py --config config.demo.json --live
```

`config.demo.json` diffère du défaut sur deux points seulement :

- `dry_run: false` — les ordres partent vraiment vers le serveur du broker ;
- `require_demo_account: true` — **le bot refuse de démarrer si le terminal est
  connecté à un compte réel**, et le dit explicitement. C'est le garde-fou qui
  évite l'erreur de compte à 2 h du matin.

Procédure complète :

1. Ouvrir un compte démo chez ton broker, se connecter avec dans MT5.
2. **Outils → Options → Expert Advisors → Autoriser le trading algorithmique.**
3. Vérifier le libellé exact du symbole BTC dans l'Observation du marché et le
   reporter dans `config.demo.json` (`BTCUSD`, `BTCUSD.a`, `Bitcoin`…).
4. Vérifier le spread réel observé sur BTC chez ce broker, et ajuster
   `risk.max_spread` en conséquence (60 $ par défaut).
5. `python run.py --config config.demo.json status` — doit afficher le compte,
   le prix et « Compte de démonstration confirmé ».
6. `python run.py --config config.demo.json --live`, puis taper `OUI`.

Pendant la démo, à surveiller dans `logs/grid_bot.log` :

| Ligne | Ce qu'elle dit |
|---|---|
| `Palier B2 armé` | un ordre limite a bien été accepté par le broker |
| `Pas de grille : X -> Y` | l'ATR a bougé, la grille s'est adaptée |
| `Paliers libérés` | un TP a été touché — c'est un scalp encaissé |
| `bloqué: spread ...` | le spread dépasse la limite, aucun ordre n'est posé |
| `ARRET RISQUE` | une limite a sauté, tout est fermé |

Commandes utiles à chaud : `status` (état complet), `flatten` (tout fermer
immédiatement), `reset` (lever un arrêt terminal).

Laisse tourner **au moins deux semaines** avant de tirer la moindre conclusion :
sur 70 jours simulés, plus d'un tiers des marchés finissent au stop, et deux
semaines ne suffisent pas à voir ça arriver.

---

## Configuration

Tout est dans `config.json` (copie de `config.example.json`). Une clé inconnue
ou une valeur incohérente fait échouer le démarrage avec un message explicite —
plutôt que de trader avec un paramètre silencieusement ignoré.

**Toutes les distances sont en unités de prix (USD), pas en « points » broker.**

### `grid`

| Clé | Défaut | Rôle |
|---|---|---|
| `mode` | `both` | `both` / `long` / `short` / `trend` (direction imposée par l'EMA) |
| `levels` | `14` | paliers de chaque côté de l'ancre |
| `step_mode` | `atr` | `atr` (adaptatif) ou `fixed` |
| `step_fixed` | `250` | pas fixe si `step_mode: fixed` |
| `atr_timeframe` / `atr_period` / `atr_mult` | `M15` / `14` / `1.0` | pas = ATR × facteur |
| `step_min` / `step_max` | `200` / `800` | bornes du pas |
| `tp_mult` | `1.8` | TP = pas × ce facteur |
| `sl_mult` | `8.0` | SL individuel (0 = aucun). Doit être **> `tp_mult`** |
| `rearm_cooldown_sec` | `300` | délai avant de réarmer un palier qui vient de prendre son TP |
| `reanchor_mult` | `1.5` | seuil de re-centrage de la grille |
| `trail_grid` | `true` | laisser la grille suivre le prix **même avec des positions ouvertes** |
| `max_position_age_sec` | `0` | stop temporel, 0 = désactivé. Le calibrage montre qu'il n'aide pas ici (voir plus bas) |

### `sizing`

| Clé | Défaut | Rôle |
|---|---|---|
| `mode` | `fixed` | `fixed` (lot constant) ou `risk` (% d'equity par palier, exige `sl_mult > 0`) |
| `lot` | `0.01` | lot par palier en mode `fixed` |
| `risk_per_level_pct` | `0.25` | % d'equity risquée par palier en mode `risk` |
| `lot_max` | `0.05` | plafond dur |
| `martingale_factor` | `1.0` | volume × facteur^(palier−1). **Laisse-le à 1.0.** Au-delà, la grille finit statistiquement à zéro |

### `risk` — les garde-fous

| Clé | Défaut | Effet quand la limite est franchie |
|---|---|---|
| `max_positions` | `4` | plafond positions + ordres en attente. **Le paramètre le plus important du fichier** : c'est lui qui borne l'accumulation |
| `max_total_lots` / `max_net_lots` | `0.042` / `0.016` | exposition brute / nette (bloque l'ouverture) |
| `max_spread` | `60` | au-delà, aucun nouvel ordre — le spread BTC explose sur les news |
| `max_drawdown_pct` | `15` | **arrêt terminal** : tout est fermé, reprise seulement via `reset` |
| `daily_loss_pct` | `5` | **arrêt journalier** : tout est fermé, reprise automatique le lendemain (UTC) |
| `min_free_margin_pct` | `40` | arrêt terminal avant l'appel de marge |
| `basket_tp_currency` | `0` | > 0 : ferme tout dès que le flottant global atteint ce gain, puis re-centre |
| `basket_sl_currency` | `0` | > 0 : arrêt journalier dès que le flottant global atteint cette perte |
| `close_all_on_halt` | `true` | fermer positions et ordres lors d'un arrêt |
| `resume_next_day` | `true` | ne concerne **que** les arrêts journaliers |

La distinction est volontaire : une perte quotidienne est un mauvais jour, un
drawdown maximum est un désaveu de la stratégie. Le second ne se lève pas tout seul.

### `session`

`enabled: false` par défaut, le BTC cotant en continu chez la plupart des brokers CFD.
Sinon, `windows` accepte des fenêtres UTC `"HH:MM-HH:MM"`, y compris à cheval sur
minuit (`"22:00-04:00"`).

---

## Backtest

Le backtest rejoue **le même `GridEngine`** que le mode réel — ce qui est testé est
le code qui tradera, pas une réimplémentation approchée.

```bash
# mécanique du bot sur marche aléatoire (aucun besoin de MT5)
python backtest.py --config config.json --synthetic 20000

# marché haussier régulier : le pire cas d'une grille bidirectionnelle
python backtest.py --config config.json --synthetic 20000 --drift 0.0008

# données réelles exportées en CSV (colonnes time,open,high,low,close)
python backtest.py --config config.json --csv data/btc_m5.csv --spread 25

# historique téléchargé directement depuis le terminal MT5 (Windows)
python backtest.py --config config.json --from-mt5 --timeframe M5 --count 100000

# exports
python backtest.py -c config.json --csv data/btc_m5.csv \
    --equity-csv equity.csv --trades-csv trades.csv
```

Les caractéristiques contractuelles du symbole se règlent en ligne de commande
(`--contract-size`, `--tick-value`, `--tick-size`, `--volume-min`, `--digits`) :
**aligne-les sur ton broker**, sinon le PnL simulé ne veut rien dire. Les valeurs
par défaut correspondent à 1 lot = 1 BTC, cotation à 2 décimales.

**Ce que le backtest ne modélise pas** : slippage, requotes, élargissement du
spread sur news, swaps, gaps de week-end, coupures du serveur. Un backtest de
grille est toujours plus flatteur que le réel.

---

## Ce que la recherche de paramètres a montré

`optimize.py` fait une recherche aléatoire en trois étapes (exploration,
affinage, validation sur graines inédites), chaque candidat étant jugé sur
plusieurs régimes de marché. `validate.py` compare des configurations sur les
mêmes marchés, appariées à la graine près.

```bash
python optimize.py --space focus --candidates 150 --bars 10000 --bars-final 20000
python validate.py config.example.json config.demo.json --seeds 201-216 --bars 20000
```

Les marchés de test viennent de `grid_bot/market.py` : volatilité GARCH,
innovations de Student (queues épaisses), régimes markoviens. Volatilité
annualisée 47–92 %, kurtosis 5–11 — les propriétés statistiques du BTC. **Ce ne
sont pas de vraies données** : c'est un banc d'essai pour vérifier qu'un
réglage survit à tous les régimes, pas une prévision de rentabilité.

### Le seul résultat qui compte : la ruine croît avec le temps d'exposition

Même configuration, même jeu de graines, seul l'horizon change :

| Durée simulée | 6 000 bougies (~21 j) | 10 000 (~35 j) | 20 000 (~70 j) |
|---|---|---|---|
| Runs terminés au stop | 4,2 % | 8,3 % | **30,6 %** |

Le nombre de trades ne change presque pas ; c'est le **temps passé en position**
qui tue. Une grille échange du temps contre une perte différée.

### Ce qui a été essayé pour corriger ça — et n'a pas marché

| Piste | Résultat | Verdict |
|---|---|---|
| **Stop temporel** (fermer une position après N heures) | 2 h : +33 % ruine · 12 h : +40 % · 48 h : +33 % | pire que sans, à toutes les durées |
| **Filtre de tendance EMA** (`mode: trend`) | 43,8 % ruine contre 31,2 % en neutre | dégrade tout : te met du mauvais côté *après* le mouvement |
| **Basket SL serré** (−3 % au lieu de −15 %) | 37,5 % ruine contre 31,2 % | coupe trop tôt, rate les retours |
| **Budget de risque réduit** (8 % au lieu de 15 %) | **75 %** de ruine | resserrer le stop le fait toucher plus souvent |
| **Long seul** | survit au haussier (25 %) mais meurt au krach (100 %) | échange un risque contre un autre |
| **Short seul** | survit au baissier (0 %) mais meurt au haussier (100 %) | idem, en miroir |

Le stop temporel est resté dans le code (`grid.max_position_age_sec`, **désactivé
par défaut**) parce qu'il peut servir à d'autres réglages, mais le calibrage est
sans appel : il ne sauve rien ici.

### Rendement par régime de la configuration livrée

Validation finale, 16 graines inédites, 20 000 bougies :

| Régime | Rendement moyen | Runs au stop |
|---|---|---|
| `range` (oscillant) | **+26,9 %** | 0 % |
| `mixed` (le plus réaliste) | **+7,9 %** | 25 % |
| `chop` (volatil sans direction) | +4,8 % | 38 % |
| `crash` | −0,2 % | 44 % |
| `bear` | −6,9 % | 19 % |
| `bull` (haussier soutenu) | **−10,0 %** | **94 %** |

La grille est un pari sur l'absence de tendance. En range elle est excellente,
en tendance soutenue elle est condamnée — et aucun réglage ne change ça.

### La configuration par défaut a été remplacée

La première version livrée (pas serré à 100 $, 6 paliers, 10 positions, TP à
1 pas) atteignait **80 % de ruine** sur ce banc d'essai. Elle a été remplacée par
la géométrie validée : pas larges (ATR × 1,0, minimum 200 $), **4 positions
simultanées maximum**, TP à 1,8 pas, SL à 8 pas, 300 s de cooldown. Moins de
trades, beaucoup moins de ruine.

---

## Version MQL5 (Expert Advisor)

1. Copier `mql5/GridScalperBTC.mq5` dans
   `<dossier de données MT5>/MQL5/Experts/` (menu **Fichier → Ouvrir le dossier de données**).
2. Dans MetaEditor (F4) : ouvrir le fichier, **Compiler** (F7).
3. Glisser l'EA sur un graphique BTCUSD, cocher **Autoriser le trading algorithmique**.

Les paramètres reprennent un à un ceux du JSON. L'EA est autonome : ni Python, ni
dépendance externe, et il tourne sur un VPS MetaQuotes. Il est aussi utilisable
dans le **testeur de stratégie** de MT5, qui modélise le spread et l'exécution
bien mieux que le backtest Python.

Sous Linux, l'EA est même le chemin le plus simple : le terminal sous Wine
exécute l'EA nativement, sans Python ni pont RPyC.

Différence assumée : l'EA ne persiste pas son état sur disque. Après un
redémarrage, il retrouve ses positions par numéro magique et reconstruit sa
grille, mais son pic d'equity repart du niveau courant.

---

## Tests

```bash
python -m unittest discover -s tests -v
```

51 tests couvrent les indicateurs, la validation de configuration, la géométrie
de la grille (paliers, TP/SL, ordres qui ne croisent jamais le marché), le
dimensionnement, les garde-fous (drawdown terminal vs journalier, spread, plafond
de positions, basket TP, fenêtres de session), le stop temporel, le refus des
comptes réels en mode démo, le réalisme statistique du générateur de marchés,
la sélection du pont Linux, et des scénarios de bout en bout sur le simulateur.

Aucune dépendance de test : bibliothèque standard uniquement.

---

## Structure

```
mt5-grid-bot/
├── run.py                    # CLI : run / status / flatten / reset
├── backtest.py               # backtest sur CSV, historique MT5 ou marché simulé
├── optimize.py               # recherche de paramètres en 3 étapes + validation
├── validate.py               # comparaison appariée de plusieurs configurations
├── config.example.json       # défaut (mode papier), géométrie validée
├── config.demo.json          # compte démo : ordres réels, compte réel refusé
├── grid_bot/
│   ├── broker.py             # types communs + interface courtier
│   ├── mt5_broker.py         # adaptateur MetaTrader 5 (réel)
│   ├── paper_broker.py       # mode papier : cotations réelles, ordres simulés
│   ├── sim.py                # moteur d'exécution simulé (papier + backtest)
│   ├── grid.py               # moteur de grille
│   ├── risk.py               # garde-fous
│   ├── market.py             # marchés simulés réalistes (GARCH, Student, régimes)
│   ├── indicators.py         # ATR de Wilder, EMA
│   ├── config.py             # chargement et validation
│   ├── logger.py             # journalisation console + fichier rotatif
│   └── bot.py                # assemblage et boucle principale
├── mql5/GridScalperBTC.mq5   # Expert Advisor natif
└── tests/                    # 51 tests, bibliothèque standard uniquement
```

Le moteur ne parle qu'à l'interface `Broker` : la même logique tourne sur le
compte réel, en mode papier et en backtest, sans branche conditionnelle.

---

## Checklist avant de passer en réel

- [ ] Tu as accepté que **plus d'un marché sur trois** finit au stop de −15 %
- [ ] Backtest sur au moins un cycle complet de marché (hausse, baisse, range)
- [ ] Mode papier lancé plusieurs jours sur le compte réel visé
- [ ] Compte démo du même broker, mêmes paramètres, au moins deux semaines
      (`config.demo.json`, qui refuse de démarrer sur un compte réel)
- [ ] `max_drawdown_pct` fixé à un montant que tu acceptes de perdre **en entier**
- [ ] `martingale_factor` à `1.0`
- [ ] `lot` et `max_total_lots` compatibles avec ton levier et ta marge
- [ ] `max_spread` calibré sur le spread réel observé de ton broker sur BTC
- [ ] Terminal sur un VPS, ou machine qui ne s'éteint pas
- [ ] Tu sais lancer `flatten` en moins de dix secondes

Rien de ce qui précède ne constitue un conseil en investissement.
