---
name: mean-reversion
description: Fade and reversal playbook. Use when the user is scanning for, evaluating, entering, managing, or reviewing a mean-reversion / fade setup. Defines extended conditions, the trigger for a fade entry, hard stop placement, and profit target logic.
---

# Mean-Reversion Playbook (L2)

Fade extended moves back toward a mean. Counter-trend by definition — only taken when the move is statistically and structurally exhausted.

## Extended conditions (all required before considering a fade)

- Price > <!-- TODO: 2 --> standard deviations from the <!-- TODO: 20 --> EMA (or band of choice).
- RSI(14) > <!-- TODO: 75 --> (long-side fade) or < <!-- TODO: 25 --> (short-side fade).
- Move is **climactic**: largest range bar of the session and/or volume spike on the extension.
- HTF environment is **range** or **mean-reverting**, not strong trend. Do not fade trend days.

## Reversal trigger (must print before entry)

- Reversal candle at extension: <!-- TODO: pin bar, engulfing, exhaustion bar -->.
- Close back inside the prior bar's range.
- Optional secondary signal: divergence on RSI/MACD vs. price extreme.

## Entry

- Stop-entry beyond the reversal candle in the fade direction.
- Limit alternative: at or just inside the extreme, **only with** an active reversal candle and tight invalidation.

## Hard stop

- Beyond the extreme of the climactic move. No exceptions: this is a counter-trend trade and the wrong-side risk is the trade's defining feature.
- Hard floor: stop distance must not exceed <!-- TODO: 1.0 --> ATR(14).
- If structural stop > max risk per trade in `Risk.md`, **size down**.

## Profit target logic

- **Primary target:** the mean (e.g. <!-- TODO: 20 --> EMA or VWAP).
- Scale <!-- TODO: 75% --> at primary target. Mean-reversion trades give back if held too long.
- Trail remainder under new structure with a **tight** trail. The "runner" mentality is wrong here.
- Time stop: if mean not tagged within <!-- TODO: 45 --> minutes, exit at market.

## Invalidation

- Price makes a new extreme after the reversal candle (fade failed).
- Trend day signal prints (no fades on trend days).
- Volume continues expanding in the extension direction after entry.

## Score this setup

- [ ] All extension conditions met
- [ ] HTF environment supports mean-reversion (not trend)
- [ ] Reversal candle confirmed
- [ ] Stop beyond the extreme, within ATR cap
- [ ] Primary target (mean) is at least <!-- TODO: 1.5R --> away
- [ ] Inside daily risk budget per `Risk.md`
- [ ] No major news scheduled in trade window
