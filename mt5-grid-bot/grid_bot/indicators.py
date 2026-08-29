"""Indicateurs utilises par le moteur de grille (sans dependance externe)."""

from __future__ import annotations

from collections.abc import Sequence


def true_range(high: float, low: float, prev_close: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
        period: int = 14) -> float | None:
    """ATR de Wilder. Retourne None si l'historique est insuffisant."""
    n = len(closes)
    if n < period + 1 or len(highs) != n or len(lows) != n:
        return None
    trs = [true_range(highs[i], lows[i], closes[i - 1]) for i in range(1, n)]
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def ema(values: Sequence[float], period: int) -> float | None:
    """Moyenne mobile exponentielle, amorcee par une SMA."""
    if period < 1 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for v in values[period:]:
        value = v * k + value * (1.0 - k)
    return value
