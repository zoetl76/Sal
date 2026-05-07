---
description: Score a setup against the loaded playbook, run risk-manager, and prepare an entry order — only if all checks pass.
---

Score the proposed entry against the playbook the user names (or the most recently loaded one if not named). Use the playbook's score-this-setup checklist. **Every box must be ticked** before proceeding.

Then spawn the `risk-manager` subagent with the entry, stop, and current account state. Only if risk-manager returns `APPROVED`, present the prepared order details to the user for manual placement.

If any check fails, state which one and stop. Do not "almost" approve.
