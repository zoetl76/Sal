---
description: Evaluate and prepare a hedge against an existing position.
---

Spawn `risk-manager` with the current position and the proposed hedge. The hedge must:
- Reduce net exposure, not increase total at-risk dollars
- Use an instrument with established correlation (state the assumption)
- Have its own stop, defined before the order

If the user is hedging because the original trade is wrong, point that out and offer `/cut` as the alternative. A hedge to delay accepting a loss is not a hedge — it is two losing trades.
