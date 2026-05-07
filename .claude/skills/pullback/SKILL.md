---
name: pullback
description: Trend-continuation pullback playbook. Use when the user is scanning for, evaluating, or managing a pullback entry into an established trend. Defines acceptable pullback depth, the structure required to confirm continuation, and the criteria that invalidate the setup.
---

# Pullback Playbook (L2)

Trend continuation. An established trend pauses or pulls back to a known support area, then resumes in the original direction.

## Trend qualification (must be true to even consider a pullback)

- Higher timeframe trend defined by: <!-- TODO: 50 --> EMA slope and the structure of higher highs / higher lows (long) or lower highs / lower lows (short) over the last <!-- TODO: 20 --> bars.
- Pullback must occur **into** an identifiable support: prior breakout level, moving average, VWAP, or measured-move retracement.

## Acceptable pullback depth

- Minimum: <!-- TODO: 38% --> of the prior impulse leg (avoid taking shallow noise).
- Maximum: <!-- TODO: 61.8% --> of the prior impulse leg (anything deeper is structural change, not a pullback).
- Pullback should be **corrective**: smaller bodies, overlapping bars. An impulsive counter-move invalidates.

## Confirmation rules (all required)

- A reversal pattern at the support area: <!-- TODO: bullish engulfing, hammer, double bottom, etc. -->
- Volume on the pullback declines vs. the prior impulse, then expands on the reversal candle.
- HTF bias still intact at confirmation (re-check; trends fail).

## Entry trigger

- Stop-entry above the high of the confirmation candle (long) or below its low (short).
- Alternative limit: at the support level itself, only if the confirmation pattern is already printed.

## Initial stop

- Below the pullback's swing low (long) or above swing high (short).
- Hard floor: stop distance must not exceed <!-- TODO: 1.0 --> ATR(14).
- If structural stop > max risk per trade in `Risk.md`, **size down**.

## Trade management

- Stop to break-even at <!-- TODO: +1R -->.
- Scale <!-- TODO: 50% --> at the previous swing high/low; trail the rest below new swing structure.
- Add-on (optional, only if account is in profit on the day): on a second pullback, with a stop that locks total trade in profit.

## Invalidation

- Pullback exceeds maximum depth → no longer a pullback, treat as reversal.
- Bar closes through the support area without rejection.
- HTF trend structure breaks before confirmation.

## Score this setup

- [ ] HTF trend qualified
- [ ] Pullback into identifiable support
- [ ] Depth between min and max thresholds
- [ ] Pullback structure is corrective, not impulsive
- [ ] Confirmation pattern printed
- [ ] Volume signature matches
- [ ] Stop within ATR cap and risk budget
- [ ] Inside daily risk budget per `Risk.md`
