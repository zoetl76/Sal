# Grid Scalper BTC — MetaTrader 5

Bot de scalping en grille sur **BTCUSD**, livré en deux implémentations qui partagent
la même logique :

| | Fichier | Quand l'utiliser |
|---|---|---|
| **Bot Python** | `run.py` + `grid_bot/` | pilotage du terminal via l'API `MetaTrader5`, mode papier, backtest, journalisation, tests |
| **EA MQL5** | `mql5/GridScalperBTC.mq5` | exécution native dans MT5, testeur de stratégie intégré, VPS MetaQuotes |

---

## Avertissement, en une fois et sans détour

Une grille **n'a pas de stop loss par construction**. Elle gagne un peu, très
souvent, dans un marché qui oscille — et rend tout d'un coup dans une tendance
soutenue. C'est exactement ce que montre le backtest fourni :

```
Marché sans direction (5 000 bougies)   →  +3,09 %   314 trades   100 % gagnants   DD 1,8 %
Tendance haussière soutenue             →  −15,09 %   24 trades    21 % gagnants   DD 15,1 %
```

Le taux de réussite de 100 % dans le premier cas n'est pas une performance : c'est
la signature d'une grille. Le seul chiffre qui compte est le **drawdown maximum**,
et il est ici plafonné par les garde-fous — pas par la stratégie.

Ce bot est conçu pour que la perte soit **bornée et choisie** (`max_drawdown_pct`),
pas pour être rentable par défaut. Teste-le en papier, puis en démo, longtemps,
avant d'envisager le moindre euro réel.

---

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

Le paquet `MetaTrader5` **n'existe que sous Windows** et parle au terminal MT5
installé sur la **même machine**.

```bash
git clone <ce-dépôt>
cd mt5-grid-bot
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
copy config.example.json config.json
```

Dans le terminal MT5 : **Outils → Options → Expert Advisors → Autoriser le trading
algorithmique**. Vérifie aussi le libellé exact du symbole dans l'Observation du
marché : selon le broker c'est `BTCUSD`, `BTCUSD.a`, `BTCUSD_raw`, `Bitcoin`…
et il faut le reporter dans `config.json`.

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

## Configuration

Tout est dans `config.json` (copie de `config.example.json`). Une clé inconnue
ou une valeur incohérente fait échouer le démarrage avec un message explicite —
plutôt que de trader avec un paramètre silencieusement ignoré.

**Toutes les distances sont en unités de prix (USD), pas en « points » broker.**

### `grid`

| Clé | Défaut | Rôle |
|---|---|---|
| `mode` | `both` | `both` / `long` / `short` / `trend` (direction imposée par l'EMA) |
| `levels` | `6` | paliers de chaque côté de l'ancre |
| `step_mode` | `atr` | `atr` (adaptatif) ou `fixed` |
| `step_fixed` | `250` | pas fixe si `step_mode: fixed` |
| `atr_timeframe` / `atr_period` / `atr_mult` | `M15` / `14` / `0.5` | pas = ATR × facteur |
| `step_min` / `step_max` | `100` / `1500` | bornes du pas |
| `tp_mult` | `1.0` | TP = pas × ce facteur |
| `sl_mult` | `0.0` | SL individuel (0 = aucun). Doit être **> `tp_mult`** |
| `rearm_cooldown_sec` | `30` | délai avant de réarmer un palier qui vient de prendre son TP |
| `reanchor_mult` | `1.5` | seuil de re-centrage de la grille |
| `trail_grid` | `false` | laisser la grille suivre le prix **même avec des positions ouvertes** (agressif) |

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
| `max_positions` | `10` | plafond positions + ordres en attente (bloque l'ouverture) |
| `max_total_lots` / `max_net_lots` | `0.20` / `0.15` | exposition brute / nette (bloque l'ouverture) |
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

## Version MQL5 (Expert Advisor)

1. Copier `mql5/GridScalperBTC.mq5` dans
   `<dossier de données MT5>/MQL5/Experts/` (menu **Fichier → Ouvrir le dossier de données**).
2. Dans MetaEditor (F4) : ouvrir le fichier, **Compiler** (F7).
3. Glisser l'EA sur un graphique BTCUSD, cocher **Autoriser le trading algorithmique**.

Les paramètres reprennent un à un ceux du JSON. L'EA est autonome : ni Python, ni
dépendance externe, et il tourne sur un VPS MetaQuotes. Il est aussi utilisable
dans le **testeur de stratégie** de MT5, qui modélise le spread et l'exécution
bien mieux que le backtest Python.

Différence assumée : l'EA ne persiste pas son état sur disque. Après un
redémarrage, il retrouve ses positions par numéro magique et reconstruit sa
grille, mais son pic d'equity repart du niveau courant.

---

## Tests

```bash
python -m unittest discover -s tests -v
```

27 tests couvrent les indicateurs, la validation de configuration, la géométrie
de la grille (paliers, TP/SL, ordres qui ne croisent jamais le marché), le
dimensionnement, les garde-fous (drawdown terminal vs journalier, spread, plafond
de positions, basket TP, fenêtres de session), et deux scénarios de bout en bout
sur le simulateur.

Aucune dépendance de test : bibliothèque standard uniquement.

---

## Structure

```
mt5-grid-bot/
├── run.py                    # CLI : run / status / flatten / reset
├── backtest.py               # backtest + génération de données synthétiques
├── config.example.json       # configuration commentée dans ce README
├── grid_bot/
│   ├── broker.py             # types communs + interface courtier
│   ├── mt5_broker.py         # adaptateur MetaTrader 5 (réel)
│   ├── paper_broker.py       # mode papier : cotations réelles, ordres simulés
│   ├── sim.py                # moteur d'exécution simulé (papier + backtest)
│   ├── grid.py               # moteur de grille
│   ├── risk.py               # garde-fous
│   ├── indicators.py         # ATR de Wilder, EMA
│   ├── config.py             # chargement et validation
│   ├── logger.py             # journalisation console + fichier rotatif
│   └── bot.py                # assemblage et boucle principale
├── mql5/GridScalperBTC.mq5   # Expert Advisor natif
└── tests/test_grid_bot.py
```

Le moteur ne parle qu'à l'interface `Broker` : la même logique tourne sur le
compte réel, en mode papier et en backtest, sans branche conditionnelle.

---

## Checklist avant de passer en réel

- [ ] Backtest sur au moins un cycle complet de marché (hausse, baisse, range)
- [ ] Mode papier lancé plusieurs jours sur le compte réel visé
- [ ] Compte démo du même broker, mêmes paramètres, au moins deux semaines
- [ ] `max_drawdown_pct` fixé à un montant que tu acceptes de perdre **en entier**
- [ ] `martingale_factor` à `1.0`
- [ ] `lot` et `max_total_lots` compatibles avec ton levier et ta marge
- [ ] `max_spread` calibré sur le spread réel observé de ton broker sur BTC
- [ ] Terminal sur un VPS, ou machine qui ne s'éteint pas
- [ ] Tu sais lancer `flatten` en moins de dix secondes

Rien de ce qui précède ne constitue un conseil en investissement.
