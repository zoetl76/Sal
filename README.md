# SAL — Agent de Trading S&P 500

Agent de trading intelligent sur le S&P 500, propulsé par **Claude** (Anthropic). Il analyse les indicateurs techniques en temps réel et prend des décisions d'achat/vente motivées.

## Architecture

```
├── main.py              # Point d'entrée CLI
├── config/
│   └── settings.py      # Paramètres (indicateurs, risque, capital)
└── src/
    ├── data.py          # Fetch Yahoo Finance + indicateurs techniques
    ├── signals.py       # Génération de signaux (RSI, MACD, BB, Trend, Volume)
    ├── portfolio.py     # Gestion des positions et du P&L
    ├── agent.py         # Agent Claude (moteur de décision)
    └── backtest.py      # Moteur de backtest rule-based
```

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env
# Renseigner ANTHROPIC_API_KEY dans .env
```

## Utilisation

```bash
# Voir les données de marché et indicateurs actuels
python main.py snapshot

# Obtenir une décision de trading (nécessite ANTHROPIC_API_KEY)
python main.py trade

# Backtest sur 1 an (rule-based, sans API)
python main.py backtest

# Backtest sur une période précise avec détail des trades
python main.py backtest --start 2022-01-01 --end 2024-12-31 --trades
```

## Indicateurs utilisés

| Indicateur | Paramètres | Usage |
|---|---|---|
| RSI | 14 périodes | Détection surachat/survente |
| MACD | 12/26/9 | Momentum et croisements |
| Bollinger Bands | 20/2σ | Volatilité et retour à la moyenne |
| SMA 50/200 | — | Tendance court/long terme, Golden/Death Cross |
| ATR | 14 | Volatilité absolue |
| Volume | ratio 20j | Confirmation des mouvements |

## Gestion du risque

- **Stop-loss**: -5% depuis l'entrée (automatique, avant consultation du LLM)
- **Take-profit**: +10% depuis l'entrée (automatique)
- **Exposition max**: 95% du capital par position
- **Positions**: Long uniquement (pas de short)

## Avertissement

Cet agent est un outil éducatif et expérimental. Il ne constitue pas un conseil financier. Les performances passées ne garantissent pas les performances futures.
