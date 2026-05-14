"""Agent de trading S&P 500 propulsé par Claude."""

import os
import json
import anthropic
from typing import Optional

from src.signals import Signal, compute_all_signals, score_signals
from src.portfolio import Portfolio
from config.settings import MAX_POSITION_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT

SYSTEM_PROMPT = """Tu es SAL, un agent de trading quantitatif expert sur le S&P 500.

Tu analyses des données de marché en temps réel (indicateurs techniques, signaux) et tu prends des décisions de trading objectives et disciplinées.

## Tes règles de gestion du risque
- Stop-loss automatique : fermer toute position perdant plus de {stop_loss}% depuis l'entrée
- Take-profit : sécuriser les gains au-delà de {take_profit}%
- Exposition maximale : {max_pos}% du capital par trade
- Ne jamais moyenner à la baisse

## Ton processus de décision
1. Analyser les indicateurs techniques (RSI, MACD, Bollinger, tendance, volume)
2. Évaluer le score global bullish/bearish
3. Tenir compte de la position actuelle du portefeuille
4. Formuler une décision claire avec une justification concise

## Format de réponse OBLIGATOIRE
Tu dois répondre UNIQUEMENT avec un objet JSON valide, sans markdown, sans texte avant ou après :
{{
  "action": "BUY" | "SELL" | "HOLD",
  "conviction": 1-10,
  "raison": "Explication concise (2-3 phrases max)",
  "pct_capital": 0.0-1.0,
  "risques": "Principal risque identifié"
}}

- action BUY : ouvrir/maintenir une position longue
- action SELL : fermer la position existante
- action HOLD : conserver l'état actuel (pas de trade)
- conviction : niveau de confiance (1=très faible, 10=très élevé)
- pct_capital : fraction du capital à engager (uniquement pour BUY, sinon 0)
""".format(
    stop_loss=int(STOP_LOSS_PCT * 100),
    take_profit=int(TAKE_PROFIT_PCT * 100),
    max_pos=int(MAX_POSITION_PCT * 100),
)


def _build_user_message(snapshot: dict, signals: list[Signal], score: dict, portfolio: Portfolio) -> str:
    pf = portfolio.summary(snapshot["close"])
    signals_text = "\n".join(
        f"  - [{s.direction}/{s.strength}] {s.name}: {s.description}"
        for s in signals
    )

    position_text = "Aucune position ouverte (FLAT)"
    if portfolio.position.is_open:
        upnl = portfolio.position.unrealized_pnl(snapshot["close"])
        upct = portfolio.position.unrealized_pct(snapshot["close"])
        position_text = (
            f"LONG depuis {portfolio.position.entry_date} "
            f"@ {portfolio.position.entry_price:.2f} | "
            f"P&L non réalisé: {upnl:+.2f}$ ({upct:+.2f}%)"
        )

    return f"""## Données de marché — {snapshot['date']}

### SPY (S&P 500 ETF)
- Prix: {snapshot['close']:.2f}$ (O:{snapshot['open']:.2f} H:{snapshot['high']:.2f} L:{snapshot['low']:.2f})
- Rendements: 1j={snapshot['return_1d']:+.2f}% | 5j={snapshot['return_5d']:+.2f}% | 20j={snapshot['return_20d']:+.2f}%
- Volume: {snapshot['volume']:,} (ratio vs moyenne: {snapshot['vol_ratio']:.2f}x)

### Indicateurs techniques
- RSI({14}): {snapshot['rsi']:.1f}
- MACD: {snapshot['macd']:.4f} | Signal: {snapshot['macd_signal']:.4f} | Hist: {snapshot['macd_hist']:+.4f}
- Bollinger: {snapshot['bb_lower']:.2f} / {snapshot['bb_middle']:.2f} / {snapshot['bb_upper']:.2f} (position: {snapshot['bb_pct']:.0%})
- SMA50: {snapshot['sma_50']:.2f} | SMA200: {snapshot['sma_200']:.2f} | EMA20: {snapshot['ema_20']:.2f}
- ATR(14): {snapshot['atr']:.2f}

### Signaux générés
{signals_text}

### Score technique global
- Bull: {score['bull_score']} | Bear: {score['bear_score']} | Net: {score['net_score']:+.2f}/10
- **Biais: {score['biais']}**

### Portefeuille
- Capital initial: {pf['capital_initial']:,.0f}$
- Valeur totale: {pf['valeur_totale']:,.2f}$ ({pf['rendement_pct']:+.2f}%)
- Liquidités: {pf['cash']:,.2f}$
- Position: {position_text}
- P&L réalisé: {pf['pnl_realise']:+.2f}$
- Nb trades: {pf['nb_trades']} | Taux de réussite: {pf['taux_reussite']:.1f}%

### Événements de marché
- Golden Cross: {snapshot['golden_cross']} | Death Cross: {snapshot['death_cross']}
- MACD Bull Cross: {snapshot['macd_bullish_cross']} | MACD Bear Cross: {snapshot['macd_bearish_cross']}

Quelle est ta décision de trading ?"""


class TradingAgent:
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-opus-4-7"):
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model
        self._cache_control = {"type": "ephemeral"}

    def decide(self, snapshot: dict, portfolio: Portfolio) -> dict:
        """Analyse le marché et retourne une décision de trading."""
        signals = compute_all_signals(snapshot)
        score = score_signals(signals)

        # Stop-loss / take-profit automatiques (avant même de consulter Claude)
        if portfolio.position.is_open:
            upct = portfolio.position.unrealized_pct(snapshot["close"])
            if upct <= -STOP_LOSS_PCT * 100:
                return {
                    "action": "SELL",
                    "conviction": 9,
                    "raison": f"Stop-loss déclenché: {upct:.2f}% de perte",
                    "pct_capital": 0.0,
                    "risques": "Protection du capital",
                    "signals": signals,
                    "score": score,
                    "auto": True,
                }
            if upct >= TAKE_PROFIT_PCT * 100:
                return {
                    "action": "SELL",
                    "conviction": 8,
                    "raison": f"Take-profit déclenché: +{upct:.2f}% de gain",
                    "pct_capital": 0.0,
                    "risques": "Sécurisation des gains",
                    "signals": signals,
                    "score": score,
                    "auto": True,
                }

        user_message = _build_user_message(snapshot, signals, score, portfolio)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": self._cache_control,
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )

        raw = response.content[0].text.strip()

        # Extraction robuste du JSON
        try:
            decision = json.loads(raw)
        except json.JSONDecodeError:
            import re
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                decision = json.loads(match.group())
            else:
                decision = {"action": "HOLD", "conviction": 1, "raison": "Erreur de parsing", "pct_capital": 0.0, "risques": "N/A"}

        decision["signals"] = signals
        decision["score"] = score
        decision["auto"] = False
        decision["input_tokens"] = response.usage.input_tokens
        decision["output_tokens"] = response.usage.output_tokens
        return decision
