"""Fetching des données de marché et calcul des indicateurs techniques."""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional

from config.settings import (
    TICKER, INTERVAL, LOOKBACK_DAYS,
    RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BB_PERIOD, BB_STD, SMA_SHORT, SMA_LONG,
)


def fetch_ohlcv(
    ticker: str = TICKER,
    interval: str = INTERVAL,
    lookback_days: int = LOOKBACK_DAYS,
    end_date: Optional[datetime] = None,
) -> pd.DataFrame:
    """Télécharge les données OHLCV depuis Yahoo Finance."""
    end = end_date or datetime.today()
    start = end - timedelta(days=lookback_days)

    df = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval=interval,
        auto_adjust=True,
        progress=False,
    )

    if df.empty:
        raise ValueError(f"Aucune donnée récupérée pour {ticker}")

    # Aplatir les colonnes multi-index si nécessaire
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.index = pd.to_datetime(df.index)
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les indicateurs techniques au DataFrame."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    # ── RSI ──────────────────────────────────────────────────────────────────
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    # ── MACD ─────────────────────────────────────────────────────────────────
    ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
    df["MACD"] = ema_fast - ema_slow
    df["MACD_signal"] = df["MACD"].ewm(span=MACD_SIGNAL, adjust=False).mean()
    df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

    # ── Bandes de Bollinger ───────────────────────────────────────────────────
    sma = close.rolling(BB_PERIOD).mean()
    std = close.rolling(BB_PERIOD).std()
    df["BB_upper"] = sma + BB_STD * std
    df["BB_lower"] = sma - BB_STD * std
    df["BB_middle"] = sma
    df["BB_pct"] = (close - df["BB_lower"]) / (df["BB_upper"] - df["BB_lower"])

    # ── Moyennes mobiles ──────────────────────────────────────────────────────
    df["SMA_50"] = close.rolling(SMA_SHORT).mean()
    df["SMA_200"] = close.rolling(SMA_LONG).mean()
    df["EMA_20"] = close.ewm(span=20, adjust=False).mean()

    # ── ATR (volatilité) ──────────────────────────────────────────────────────
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    df["ATR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

    # ── Volume moyen ──────────────────────────────────────────────────────────
    df["Vol_SMA_20"] = df["Volume"].rolling(20).mean()
    df["Vol_ratio"] = df["Volume"] / df["Vol_SMA_20"]

    # ── Rendements ────────────────────────────────────────────────────────────
    df["Return_1d"] = close.pct_change()
    df["Return_5d"] = close.pct_change(5)
    df["Return_20d"] = close.pct_change(20)

    return df.dropna()


def get_market_data(
    ticker: str = TICKER,
    interval: str = INTERVAL,
    lookback_days: int = LOOKBACK_DAYS,
    end_date: Optional[datetime] = None,
) -> pd.DataFrame:
    """Pipeline complet: fetch + indicateurs."""
    df = fetch_ohlcv(ticker, interval, lookback_days, end_date)
    df = add_indicators(df)
    return df


def get_latest_snapshot(df: pd.DataFrame) -> dict:
    """Retourne un dictionnaire des valeurs les plus récentes."""
    last = df.iloc[-1]
    prev = df.iloc[-2]
    return {
        "date": str(df.index[-1].date()),
        "close": round(float(last["Close"]), 2),
        "open": round(float(last["Open"]), 2),
        "high": round(float(last["High"]), 2),
        "low": round(float(last["Low"]), 2),
        "volume": int(last["Volume"]),
        "rsi": round(float(last["RSI"]), 2),
        "macd": round(float(last["MACD"]), 4),
        "macd_signal": round(float(last["MACD_signal"]), 4),
        "macd_hist": round(float(last["MACD_hist"]), 4),
        "bb_upper": round(float(last["BB_upper"]), 2),
        "bb_lower": round(float(last["BB_lower"]), 2),
        "bb_pct": round(float(last["BB_pct"]), 3),
        "sma_50": round(float(last["SMA_50"]), 2),
        "sma_200": round(float(last["SMA_200"]), 2),
        "ema_20": round(float(last["EMA_20"]), 2),
        "atr": round(float(last["ATR"]), 2),
        "vol_ratio": round(float(last["Vol_ratio"]), 2),
        "return_1d": round(float(last["Return_1d"]) * 100, 2),
        "return_5d": round(float(last["Return_5d"]) * 100, 2),
        "return_20d": round(float(last["Return_20d"]) * 100, 2),
        # Contexte marché
        "above_sma50": bool(last["Close"] > last["SMA_50"]),
        "above_sma200": bool(last["Close"] > last["SMA_200"]),
        "golden_cross": bool(last["SMA_50"] > last["SMA_200"] and prev["SMA_50"] <= prev["SMA_200"]),
        "death_cross": bool(last["SMA_50"] < last["SMA_200"] and prev["SMA_50"] >= prev["SMA_200"]),
        "macd_bullish_cross": bool(last["MACD"] > last["MACD_signal"] and prev["MACD"] <= prev["MACD_signal"]),
        "macd_bearish_cross": bool(last["MACD"] < last["MACD_signal"] and prev["MACD"] >= prev["MACD_signal"]),
    }
