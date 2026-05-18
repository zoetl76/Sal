# Polymarket Trading Bot

An asynchronous trading bot for Polymarket prediction markets, built with Python and designed for high-performance data collection, strategy evaluation, and automated trading.

## Architecture

The bot is organized into a multi-layered architecture:

1. **WebSocket Layer** (`polymarket_bot/websocket/`) - Manages multiple concurrent WebSocket connections to Polymarket for real-time order book and trade data. Implements connection pooling, automatic reconnection with exponential backoff, and jitter detection.

2. **Data Recording** (`polymarket_bot/data/`) - Stores raw and processed market data in SQLite via aiosqlite. Supports both real-time recording and batch imports for backtesting.

3. **External Feeds** (`polymarket_bot/feeds/`) - Integrates with Binance and Coinbase WebSocket APIs for external price reference data (crypto prices, etc.).

4. **Strategy Framework** (`polymarket_bot/strategy/`) - Pluggable strategy system with a base class and templates. Strategies receive normalized market events and produce trading signals.

5. **Risk Management** (`polymarket_bot/risk/`) - Stop-loss engine, position sizing, and exposure limits. Configurable per-strategy and globally.

6. **Backtesting Engine** (`polymarket_bot/backtest/`) - Replay historical data through strategies with parameter sweeps. Produces performance metrics for strategy optimization.

7. **Deployment & Monitoring** (`polymarket_bot/deploy/`) - Runner infrastructure for live, dry-run, and record-only modes. Health checks, metrics, and graceful shutdown handling.

8. **Configuration** (`polymarket_bot/config.py`) - Unified configuration from environment variables, .env files, and YAML configs with clear precedence rules.

## Setup

### Prerequisites

- Python 3.11+
- pyenv (recommended for version management)

### Installation

```bash
# Clone and navigate to project
cd polymarket-bot

# Set Python version
pyenv shell 3.11.15

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your API keys
```

## Usage

The bot supports four operation modes:

### Live Trading

```bash
python -m polymarket_bot.main live
```

Real trading with live market connections. Requires valid API keys.

### Dry-Run Mode

```bash
python -m polymarket_bot.main dry-run
```

Simulated trading with live data. Executes strategy logic but does not place real orders. Useful for validating strategies before going live.

### Backtest Mode

```bash
python -m polymarket_bot.main backtest
```

Replays historical data through strategies. Supports parameter sweeps and generates performance reports.

### Record-Only Mode

```bash
python -m polymarket_bot.main record-only
```

Records live market data without executing any trading logic. Use this to build a historical dataset for backtesting.

### Additional Options

```bash
# Specify custom config file
python -m polymarket_bot.main live --config path/to/config.yaml

# Override log level
python -m polymarket_bot.main dry-run --log-level DEBUG

# Use console-friendly log format
python -m polymarket_bot.main record-only --log-format console

# Target a specific market
python -m polymarket_bot.main live --market-id <condition_id>
```

## Configuration

Configuration is loaded with the following precedence (highest first):

1. **Environment variables** - Direct env vars override everything
2. **.env file** - Loaded from project root (or specified path)
3. **YAML config** - Base configuration from `config/default.yaml`

### Key Configuration Sections

| Section | Description |
|---------|-------------|
| `api` | API keys for Polymarket, Binance, Coinbase |
| `websocket` | Connection pool size, reconnect timing, jitter thresholds |
| `trading` | Price filters, stop-loss defaults, position limits |
| `data` | Storage paths, database location, raw message recording |
| `logging` | Log level, output format, file path |

See `config/default.yaml` for all available options and their defaults.

## Project Structure

```
polymarket-bot/
├── polymarket_bot/       # Main package
│   ├── __init__.py
│   ├── config.py         # Configuration management
│   ├── logging_setup.py  # Structured logging setup
│   ├── main.py           # CLI entry point
│   ├── websocket/        # WebSocket connection management
│   ├── data/             # Data recording and storage
│   ├── feeds/            # External price feeds
│   ├── strategy/         # Strategy framework
│   ├── risk/             # Risk management
│   ├── backtest/         # Backtesting engine
│   └── deploy/           # Deployment and monitoring
├── tests/                # Test suite
├── config/               # YAML configuration files
│   └── default.yaml
├── requirements.txt      # Python dependencies
├── .env.example          # Environment variable template
└── README.md             # This file
```

## Development

### Running Tests

```bash
python -m pytest tests/ -v
```

### Code Style

- Type hints on all public functions
- Docstrings following Google style
- PEP 8 compliance
- Async-first design patterns
