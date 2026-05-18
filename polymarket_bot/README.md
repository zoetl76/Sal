# 🤖 Polymarket Automatic Trading Bot

A fully automated trading bot for the [Polymarket](https://polymarket.com) prediction market platform.

## Features

- **Multiple Strategies**: Value, Momentum, Mean Reversion
- **Risk Management**: Stop loss, take profit, position sizing, exposure limits
- **Paper Trading**: Test strategies without risking real funds
- **Telegram Notifications**: Get alerts on trades, stop losses, and daily summaries
- **Auto-Discovery**: Scans markets and finds opportunities automatically
- **Graceful Shutdown**: Cancels all orders on stop signal

## Architecture

```
polymarket_bot/
├── bot.py            # Main orchestrator & trading loop
├── client.py         # Polymarket API client (Gamma, CLOB, Data)
├── strategy.py       # Trading strategies (Value, Momentum, Mean Reversion)
├── risk_manager.py   # Risk management & position tracking
├── notifier.py       # Telegram notifications
├── config.py         # Configuration management
├── .env.example      # Environment variables template
└── requirements.txt  # Python dependencies
```

## Quick Start

### 1. Install Dependencies

```bash
cd polymarket_bot
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your wallet & strategy settings
```

### 3. Run in Paper Trading Mode (Recommended First)

```bash
python bot.py
```

The bot starts in **paper trading mode by default** — no real orders are placed.

### 4. Go Live

Set `PAPER_TRADING=false` in your `.env` file once you're satisfied with the strategy.

## Configuration

### Wallet Setup

You need a Polygon wallet with:
- **pUSD** for buying outcome tokens
- A **deposit wallet** (recommended for new API users, signature type 3)
- API credentials (auto-derived from your private key on first run)

### Strategy Options

| Strategy | Description | Best For |
|----------|-------------|----------|
| `value` | Orderbook imbalance + momentum signals | Low-frequency |
| `momentum` | Follows strong price movements | Trending markets |
| `mean_reversion` | Bets against extreme moves | Volatile markets |

### Risk Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_TOTAL_EXPOSURE` | $500 | Maximum portfolio exposure |
| `STOP_LOSS` | 15% | Stop loss per position |
| `TAKE_PROFIT` | 30% | Take profit per position |
| `DAILY_LOSS_LIMIT` | $50 | Bot halts if daily losses exceed this |
| `ORDER_SIZE` | $10 | Base order size per trade |
| `MAX_POSITION_SIZE` | $100 | Max per-market exposure |

## How It Works

### Trading Loop (every 60s by default)

1. **Monitor** existing positions for stop loss / take profit
2. **Discover** active markets via Gamma API
3. **Filter** markets by liquidity, volume, and orderbook availability
4. **Analyze** filtered markets using the selected strategy
5. **Validate** signals through risk manager
6. **Execute** approved signals as limit orders
7. **Report** portfolio state

### Market Selection Criteria

- Must have active orderbook
- Must meet minimum liquidity threshold ($1000 default)
- Must have reasonable spread (< 10%)
- Scored by volume, liquidity, and price characteristics

### Signal Generation (Value Strategy Example)

1. Fetch orderbook for each candidate market
2. Calculate bid/ask imbalance
3. If strong imbalance detected (>30%), generate signal
4. Boost confidence with momentum confirmation
5. Filter signals by minimum edge requirement

## Safety Features

- **Paper trading mode** enabled by default
- **Daily loss limit** halts trading automatically
- **Position size limits** prevent over-concentration
- **Exposure cap** limits total portfolio risk
- **Graceful shutdown** cancels all orders on SIGINT/SIGTERM
- **Comprehensive logging** with daily rotation

## Telegram Notifications

Enable notifications by setting in `.env`:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

You'll receive alerts for:
- 🔔 Trade executions
- ⚠️ Stop loss triggers
- ✅ Take profit events
- 📊 Daily summaries
- 🚨 Critical errors

## Important Notes

- **Geographic Restrictions**: Polymarket is not available in all regions. Check the [geoblock docs](https://docs.polymarket.com/api-reference/geoblock).
- **Not Financial Advice**: This bot is for educational purposes. Use at your own risk.
- **Test First**: Always start with paper trading to validate your strategy.
- **Fees**: Polymarket charges taker fees on most markets. Factor this into your strategy.

## License

MIT
