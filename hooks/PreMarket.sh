#!/usr/bin/env bash
# PreMarket.sh — Layer 3 Guardrail Hook
# Runs before the session opens. Loads context and produces a structured briefing.
#
# Output: prints to stdout AND appends to journal/sessions/YYYY-MM-DD/premarket.md

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATE="$(date +%Y-%m-%d)"
SESSION_DIR="${ROOT}/journal/sessions/${DATE}"
mkdir -p "${SESSION_DIR}"

OUTFILE="${SESSION_DIR}/premarket.md"

# --- TODO: replace these stubs with broker/data feed calls ---
INSTRUMENT="${INSTRUMENT:-<INSTRUMENT>}"
OVERNIGHT_HIGH="<TODO: fetch>"
OVERNIGHT_LOW="<TODO: fetch>"
PRIOR_CLOSE="<TODO: fetch>"
ATR14="<TODO: fetch>"
NEWS_NEXT_4H="<TODO: fetch from economic calendar>"

# Regime: trend if last close outside prior day's range; else range. Stub.
REGIME="<TODO: trend|range>"

cat <<EOF | tee "${OUTFILE}"
# Pre-Market Briefing — ${DATE}

## Instrument
- ${INSTRUMENT}

## Overnight structure
- High: ${OVERNIGHT_HIGH}
- Low:  ${OVERNIGHT_LOW}
- Prior close: ${PRIOR_CLOSE}
- ATR(14): ${ATR14}

## Regime
- ${REGIME}

## Bias
- <TODO: long | short | neutral, with one-line reason>

## Key levels (act on these, not on hunches)
- R2:
- R1:
- VWAP / pivot:
- S1:
- S2:

## Scheduled events (next 4h)
${NEWS_NEXT_4H}

## Session risk frame
- Max daily loss: see Risk.md
- Trades remaining today: <TODO: max trades - executed>
- No-trade windows: <TODO: e.g. 10:00 CPI ±15min>

## Active playbook(s) for today
- <TODO: breakout | pullback | mean-reversion>
EOF

echo
echo "Briefing written to ${OUTFILE}"
