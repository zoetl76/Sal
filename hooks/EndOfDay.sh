#!/usr/bin/env bash
# EndOfDay.sh — Layer 3 Guardrail Hook
# Runs before the close. Saves session state, captures P&L, prepares journal entry.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATE="$(date +%Y-%m-%d)"
SESSION_DIR="${ROOT}/journal/sessions/${DATE}"
mkdir -p "${SESSION_DIR}"

LOG="${ROOT}/trades.log"
JOURNAL="${SESSION_DIR}/journal.md"

TRADES_TODAY=0
if [[ -f "$LOG" ]]; then
  TRADES_TODAY=$(grep -c "\"ts\":\"${DATE}T" "$LOG" || true)
fi

cat > "${JOURNAL}" <<EOF
# Session Journal — ${DATE}

## Numbers
- Trades executed: ${TRADES_TODAY}
- Wins / losses: <TODO>
- Largest win: <TODO>
- Largest loss: <TODO>
- Net P&L: <TODO>

## Rule check (against CLAUDE.md and Risk.md)
- [ ] Stayed inside trading window
- [ ] Every entry had a stop placed before the order
- [ ] No stops moved against
- [ ] Did not exceed max trades / max daily loss
- [ ] Took only setups defined in playbooks
- [ ] Tilt control rule respected after consecutive losers

## Violations (be specific — file:section)
-

## Best trade today (and why it worked)
-

## Worst trade today (and the rule that would have prevented it)
-

## Three corrections for tomorrow
1.
2.
3.
EOF

echo "session state saved: ${JOURNAL}"
echo "next: open it and fill in the numbers; run journal-analyzer over the last 30 trades."
