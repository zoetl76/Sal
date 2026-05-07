---
description: Close all open positions and close the session cleanly.
---

Confirm the close with the user, then:
1. Log each exit via `hooks/PostTrade.sh`.
2. Run `hooks/EndOfDay.sh`.
3. Open the prepared journal at `journal/sessions/<today>/journal.md` and walk the user through the rule check.
4. Spawn `journal-analyzer` if the trades.log has at least 10 entries.
