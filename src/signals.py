"""Génération de signaux techniques à partir des indicateurs."""

from dataclasses import dataclass
from typing import Literal

SignalStrength = Literal["FORT", "MODERE", "FAIBLE", "NEUTRE"]
SignalDirection = Literal["BULLISH", "BEARISH", "NEUTRE"]


@dataclass
class Signal:
    name: str
    direction: SignalDirection
    strength: SignalStrength
    value: float
    description: str


def rsi_signal(rsi: float) -> Signal:
    if rsi < 30:
        return Signal("RSI", "BULLISH", "FORT", rsi, f"RSI survendu à {rsi:.1f} — rebond probable")
    elif rsi < 40:
        return Signal("RSI", "BULLISH", "MODERE", rsi, f"RSI bas à {rsi:.1f} — zone d'achat")
    elif rsi > 70:
        return Signal("RSI", "BEARISH", "FORT", rsi, f"RSI suracheté à {rsi:.1f} — correction probable")
    elif rsi > 60:
        return Signal("RSI", "BEARISH", "MODERE", rsi, f"RSI élevé à {rsi:.1f} — prudence")
    else:
        return Signal("RSI", "NEUTRE", "NEUTRE", rsi, f"RSI neutre à {rsi:.1f}")


def macd_signal(macd: float, macd_sig: float, macd_hist: float, bullish_cross: bool, bearish_cross: bool) -> Signal:
    if bullish_cross:
        return Signal("MACD", "BULLISH", "FORT", macd_hist, "Croisement haussier du MACD — signal d'achat")
    elif bearish_cross:
        return Signal("MACD", "BEARISH", "FORT", macd_hist, "Croisement baissier du MACD — signal de vente")
    elif macd > macd_sig and macd_hist > 0:
        return Signal("MACD", "BULLISH", "MODERE", macd_hist, f"MACD au-dessus du signal (+{macd_hist:.4f})")
    elif macd < macd_sig and macd_hist < 0:
        return Signal("MACD", "BEARISH", "MODERE", macd_hist, f"MACD sous le signal ({macd_hist:.4f})")
    else:
        return Signal("MACD", "NEUTRE", "NEUTRE", macd_hist, "MACD indécis")


def bollinger_signal(bb_pct: float, close: float, bb_upper: float, bb_lower: float) -> Signal:
    if bb_pct < 0.05:
        return Signal("BB", "BULLISH", "FORT", bb_pct, f"Prix ({close:.2f}) sous la bande basse ({bb_lower:.2f}) — survente")
    elif bb_pct < 0.2:
        return Signal("BB", "BULLISH", "MODERE", bb_pct, f"Prix proche de la bande basse ({bb_lower:.2f})")
    elif bb_pct > 0.95:
        return Signal("BB", "BEARISH", "FORT", bb_pct, f"Prix ({close:.2f}) au-dessus de la bande haute ({bb_upper:.2f}) — surachat")
    elif bb_pct > 0.8:
        return Signal("BB", "BEARISH", "MODERE", bb_pct, f"Prix proche de la bande haute ({bb_upper:.2f})")
    else:
        return Signal("BB", "NEUTRE", "NEUTRE", bb_pct, f"Prix dans les bandes (position: {bb_pct:.0%})")


def trend_signal(close: float, sma50: float, sma200: float, golden_cross: bool, death_cross: bool) -> Signal:
    if golden_cross:
        return Signal("TREND", "BULLISH", "FORT", close, "Golden Cross: SMA50 croise SMA200 à la hausse")
    elif death_cross:
        return Signal("TREND", "BEARISH", "FORT", close, "Death Cross: SMA50 croise SMA200 à la baisse")
    elif close > sma50 > sma200:
        return Signal("TREND", "BULLISH", "MODERE", close, f"Tendance haussière confirmée (prix > SMA50 > SMA200)")
    elif close < sma50 < sma200:
        return Signal("TREND", "BEARISH", "MODERE", close, f"Tendance baissière confirmée (prix < SMA50 < SMA200)")
    elif close > sma200:
        return Signal("TREND", "BULLISH", "FAIBLE", close, "Prix au-dessus de SMA200 (tendance long terme haussière)")
    else:
        return Signal("TREND", "BEARISH", "FAIBLE", close, "Prix sous SMA200 (tendance long terme baissière)")


def volume_signal(vol_ratio: float) -> Signal:
    if vol_ratio > 2.0:
        return Signal("VOLUME", "BULLISH", "FORT", vol_ratio, f"Volume x{vol_ratio:.1f} la moyenne — mouvement fort")
    elif vol_ratio > 1.5:
        return Signal("VOLUME", "BULLISH", "MODERE", vol_ratio, f"Volume x{vol_ratio:.1f} la moyenne — confirmation")
    elif vol_ratio < 0.5:
        return Signal("VOLUME", "NEUTRE", "FAIBLE", vol_ratio, "Volume faible — manque de conviction")
    else:
        return Signal("VOLUME", "NEUTRE", "NEUTRE", vol_ratio, f"Volume normal (ratio: {vol_ratio:.2f})")


def compute_all_signals(snapshot: dict) -> list[Signal]:
    """Calcule tous les signaux à partir d'un snapshot de marché."""
    signals = [
        rsi_signal(snapshot["rsi"]),
        macd_signal(
            snapshot["macd"], snapshot["macd_signal"], snapshot["macd_hist"],
            snapshot["macd_bullish_cross"], snapshot["macd_bearish_cross"],
        ),
        bollinger_signal(snapshot["bb_pct"], snapshot["close"], snapshot["bb_upper"], snapshot["bb_lower"]),
        trend_signal(
            snapshot["close"], snapshot["sma_50"], snapshot["sma_200"],
            snapshot["golden_cross"], snapshot["death_cross"],
        ),
        volume_signal(snapshot["vol_ratio"]),
    ]
    return signals


def score_signals(signals: list[Signal]) -> dict:
    """Calcule un score global bullish/bearish (-10 à +10)."""
    weights = {"FORT": 3, "MODERE": 2, "FAIBLE": 1, "NEUTRE": 0}
    bull_score = 0
    bear_score = 0

    for s in signals:
        w = weights[s.strength]
        if s.direction == "BULLISH":
            bull_score += w
        elif s.direction == "BEARISH":
            bear_score += w

    net = bull_score - bear_score
    max_possible = sum(weights["FORT"] for _ in signals)
    normalized = net / max_possible * 10 if max_possible > 0 else 0

    if normalized >= 4:
        bias = "FORTEMENT HAUSSIER"
    elif normalized >= 1.5:
        bias = "HAUSSIER"
    elif normalized <= -4:
        bias = "FORTEMENT BAISSIER"
    elif normalized <= -1.5:
        bias = "BAISSIER"
    else:
        bias = "NEUTRE"

    return {
        "bull_score": bull_score,
        "bear_score": bear_score,
        "net_score": round(normalized, 2),
        "biais": bias,
    }
