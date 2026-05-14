"""Moteur de backtest: rejoue la stratégie sur données historiques."""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional

from src.data import get_market_data, get_latest_snapshot, add_indicators
from src.signals import compute_all_signals, score_signals
from src.portfolio import Portfolio
from config.settings import INITIAL_CAPITAL, TICKER, MAX_POSITION_PCT


def _rule_based_decision(snapshot: dict, portfolio: Portfolio) -> dict:
    """
    Stratégie rule-based (pas d'appel LLM) pour le backtest rapide.
    Combine RSI, MACD et tendance pour générer un signal.
    """
    signals = compute_all_signals(snapshot)
    score = score_signals(signals)

    # Stop-loss / take-profit
    if portfolio.position.is_open:
        upct = portfolio.position.unrealized_pct(snapshot["close"])
        if upct <= -5.0:
            return {"action": "SELL", "raison": f"Stop-loss {upct:.2f}%", "pct_capital": 0.0}
        if upct >= 10.0:
            return {"action": "SELL", "raison": f"Take-profit +{upct:.2f}%", "pct_capital": 0.0}

    net = score["net_score"]

    if not portfolio.position.is_open:
        if net >= 3.0:
            return {"action": "BUY", "raison": f"Score haussier: {net:+.2f}", "pct_capital": MAX_POSITION_PCT}
        return {"action": "HOLD", "raison": "Signal insuffisant", "pct_capital": 0.0}
    else:
        if net <= -2.0:
            return {"action": "SELL", "raison": f"Score baissier: {net:+.2f}", "pct_capital": 0.0}
        return {"action": "HOLD", "raison": "Position maintenue", "pct_capital": 0.0}


def run_backtest(
    ticker: str = TICKER,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    initial_capital: float = INITIAL_CAPITAL,
    verbose: bool = False,
) -> dict:
    """
    Lance un backtest rule-based sur la période spécifiée.
    Retourne les métriques de performance.
    """
    end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.today()
    start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None

    lookback = 400  # assez pour calculer SMA200
    if start:
        lookback = (end - start).days + 250

    df = get_market_data(ticker=ticker, lookback_days=lookback, end_date=end)

    if start:
        df = df[df.index >= pd.Timestamp(start)]

    portfolio = Portfolio(initial_capital)
    equity_curve = []
    trade_log = []

    for i in range(1, len(df)):
        window = df.iloc[: i + 1]
        snapshot = get_latest_snapshot(window)
        current_price = snapshot["close"]
        current_date = snapshot["date"]

        decision = _rule_based_decision(snapshot, portfolio)

        if decision["action"] == "BUY" and not portfolio.position.is_open:
            trade = portfolio.buy(current_price, decision["pct_capital"], current_date, decision["raison"])
            if trade and verbose:
                print(f"[{current_date}] BUY  @ {current_price:.2f} — {decision['raison']}")
            if trade:
                trade_log.append({"date": current_date, "action": "BUY", "price": current_price, "raison": decision["raison"]})

        elif decision["action"] == "SELL" and portfolio.position.is_open:
            trade = portfolio.sell(current_price, current_date, decision["raison"])
            if trade and verbose:
                pnl = (current_price - portfolio.trades[-2].price) * trade.shares
                print(f"[{current_date}] SELL @ {current_price:.2f} — {decision['raison']} | P&L: {pnl:+.2f}$")
            if trade:
                trade_log.append({"date": current_date, "action": "SELL", "price": current_price, "raison": decision["raison"]})

        equity_curve.append({"date": current_date, "equity": portfolio.total_value(current_price)})

    # Fermer position ouverte en fin de période
    if portfolio.position.is_open:
        last_price = float(df.iloc[-1]["Close"])
        last_date = str(df.index[-1].date())
        portfolio.sell(last_price, last_date, "Fin du backtest")

    # ── Métriques ─────────────────────────────────────────────────────────────
    eq_series = [e["equity"] for e in equity_curve]
    final_value = portfolio.total_value(float(df.iloc[-1]["Close"]))
    total_return = (final_value - initial_capital) / initial_capital * 100

    # Buy & hold benchmark
    bh_start = float(df.iloc[0]["Close"])
    bh_end = float(df.iloc[-1]["Close"])
    bh_return = (bh_end - bh_start) / bh_start * 100

    # Sharpe ratio (annualisé, 252 jours)
    returns = pd.Series(eq_series).pct_change().dropna()
    sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0.0

    # Max drawdown
    peak = pd.Series(eq_series).cummax()
    drawdown = (pd.Series(eq_series) - peak) / peak
    max_dd = float(drawdown.min() * 100)

    # Win rate
    buys = [t for t in trade_log if t["action"] == "BUY"]
    sells = [t for t in trade_log if t["action"] == "SELL"]
    wins = sum(1 for b, s in zip(buys, sells) if s["price"] > b["price"])
    win_rate = wins / len(sells) * 100 if sells else 0.0

    return {
        "periode": f"{df.index[0].date()} → {df.index[-1].date()}",
        "capital_initial": initial_capital,
        "capital_final": round(final_value, 2),
        "rendement_strategie": round(total_return, 2),
        "rendement_buy_hold": round(bh_return, 2),
        "alpha": round(total_return - bh_return, 2),
        "sharpe_ratio": round(float(sharpe), 3),
        "max_drawdown_pct": round(max_dd, 2),
        "nb_trades": len(buys),
        "win_rate_pct": round(win_rate, 1),
        "equity_curve": equity_curve,
        "trade_log": trade_log,
    }
