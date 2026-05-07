# Risk.md — Hard Risk Rules (Layer 1)

> These numbers keep me in the game tomorrow. They are not negotiable.
> Personal account-specific overrides go in `Risk.local.md` (gitignored).

---

## Account

| Field | Value |
|---|---|
| Account size | <!-- TODO: $X --> |
| Currency | <!-- TODO: USD --> |
| Broker | <!-- TODO: --> |

## Per-trade limits

| Limit | Value |
|---|---|
| Max risk per trade (% of account) | <!-- TODO: 0.5% --> |
| Max risk per trade ($) | <!-- TODO: computed from above --> |
| Max position size (notional) | <!-- TODO: e.g. 25% of account --> |
| Max leverage | <!-- TODO: e.g. 2x --> |

## Daily limits

| Limit | Value |
|---|---|
| Max daily drawdown ($) | <!-- TODO: e.g. 2% of account --> |
| Max daily drawdown (% of account) | <!-- TODO: 2% --> |
| Max trades per day | <!-- TODO: 3 --> |
| Max consecutive losers before stop | <!-- TODO: 2 --> |

## Stop-loss logic

- Every entry has a hard stop, placed **before** the entry order is sent.
- Stops are based on structure (invalidation level), not on a fixed dollar amount alone.
- Once placed, a stop **only moves toward break-even or in the direction of the trade**, never against.
- If structure changes such that the original stop is no longer correct, the trade is exited at market — not adjusted.

## Drawdown response

| Drawdown level | Response |
|---|---|
| Day at -1R | Reduce next trade size by 50% |
| Day at max daily loss | Platform closed for the day. Journal mandatory. |
| Week at -3 max-daily-loss equivalents | Stop trading for the week, full review |
| Month at -10% | System review before any new trades |

## What violates this file

The following are immediate, automatic violations:
- Sizing up to "make it back"
- Removing or widening a stop
- Entering without a stop in place
- Trading after max daily loss is hit
- Trading outside the session window from `CLAUDE.md`

Claude must refuse to assist with any of these and cite this file.
