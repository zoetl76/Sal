TICKER = "SPY"          # S&P 500 ETF (proxy du SP500)
INTERVAL = "1d"         # Fréquence des données
LOOKBACK_DAYS = 365     # Historique pour les indicateurs
INITIAL_CAPITAL = 100_000.0  # Capital initial en USD

# Paramètres des indicateurs techniques
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_PERIOD = 20
BB_STD = 2.0
SMA_SHORT = 50
SMA_LONG = 200

# Gestion du risque
MAX_POSITION_PCT = 0.95   # Max 95% du capital en position
STOP_LOSS_PCT = 0.05      # Stop-loss à -5%
TAKE_PROFIT_PCT = 0.10    # Take-profit à +10%
