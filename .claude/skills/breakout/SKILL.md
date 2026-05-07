---
name: breakout
description: Momentum continuation playbook. Use when the user is scanning for, evaluating, entering, managing, or reviewing a breakout setup. Defines what constitutes a valid breakout, the confirmation required, the entry trigger, stop placement, and the conditions that invalidate the setup.
---

# Breakout Playbook (L2)

Momentum continuation. Price exits a defined range/level on expanding participation and continues in the breakout direction.

## Valid breakout structure

- A clearly defined level: prior swing high/low, range high/low, or VWAP/HOD/LOD on session timeframe.
- Range must have been respected at least <!-- TODO: 2 --> times before the break.
- Compression into the level: the last <!-- TODO: 3 --> bars contracting (range narrowing).
- Breakout candle closes **beyond** the level (not just wicks through).

## Confirmation rules (all required)

- Volume on the breakout candle ≥ <!-- TODO: 1.5x --> the 20-bar average volume.
- No major scheduled news within the next <!-- TODO: 15 --> minutes.
- Higher-timeframe bias not opposing (do not fade the HTF trend).

## Entry trigger

- **Primary:** market on the open of the next bar after the confirmed breakout close.
- **Pullback variant:** limit order at the broken level on first retest, only valid within <!-- TODO: 5 --> bars of break.

## Initial stop

- Below the breakout candle's low (long) or above its high (short).
- Hard floor: stop distance must not exceed <!-- TODO: 0.75 --> ATR(14).
- If structural stop > max risk per trade in `Risk.md`, **size down**, do not move the stop.

## Trade management

- Move stop to break-even after price travels <!-- TODO: +1R -->.
- Scale out <!-- TODO: 50% --> at <!-- TODO: +2R -->, trail the rest under the most recent swing.
- Time stop: if neither stop nor first scale hit within <!-- TODO: 60 --> minutes, exit at market.

## Invalidation (do not take, or exit if already in)

- Breakout candle reverses and closes back inside the range within <!-- TODO: 2 --> bars (failed breakout).
- Volume contracts on the breakout (no participation).
- HTF reversal signal prints on entry timeframe.

## Score this setup (use before entry)

Run through the checklist; every box must be ticked:

- [ ] Range/level meets "valid structure" definition above
- [ ] Compression into the level
- [ ] Breakout candle closes beyond the level
- [ ] Volume confirmation
- [ ] No blocking news
- [ ] HTF bias aligned (or neutral)
- [ ] Stop distance within ATR cap and risk budget
- [ ] Inside daily risk budget per `Risk.md`
