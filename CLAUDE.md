# CLAUDE.md — Global Memory (Layer 1)

> Always loaded. Every rule that governs how I trade lives here.
> Rules over feelings. If it isn't written here, it isn't part of the system.

---

## trading.rules

**Style:** <!-- TODO: e.g. intraday momentum, swing breakout, scalping -->
**Markets:** <!-- TODO: e.g. ES futures, BTC perp, SPY 0DTE options -->
**Timeframes:** <!-- TODO: e.g. 5m primary, 1h context, daily bias -->
**Edge (one sentence):** <!-- TODO: describe the repeatable inefficiency you exploit -->

### Entry model
- I only enter when a setup defined in `.claude/skills/<setup>/SKILL.md` is fully validated.
- No setup = no trade. Boredom is not a setup.
- Confirmation required before entry: <!-- TODO: e.g. volume expansion + close above level -->

### No-trade conditions
- First/last 15 minutes of session unless the playbook explicitly allows it.
- Major scheduled news in the next <!-- TODO: 30 --> minutes, unless the playbook is a news-driven setup.
- Average true range below <!-- TODO: threshold -->.
- I have already hit max daily loss or max trades for the day (see `Risk.md`).

---

## risk.rules

See `Risk.md` for hard numbers. CLAUDE.md must never override Risk.md.

- All trades sized off **dollar risk**, never share/contract count.
- Stop is set **before** the entry order is sent. No exceptions.
- I do not move stops against me. Ever.

---

## execution.workflow

1. **Pre-trade checklist** (must pass all):
   - [ ] Setup matches a loaded playbook
   - [ ] Confirmation criteria met
   - [ ] Stop level identified and risk in $ calculated
   - [ ] Inside daily risk budget (`Risk.md`)
   - [ ] No blocking news in window
2. **Entry trigger:** specified by the playbook, not my discretion.
3. **Trade management:** scaling/trailing rules live in the playbook, not in my head.
4. **Exit plan:** target or trail, defined before entry. Time-stop after <!-- TODO: 60 --> minutes if neither hit.

---

## session.behavior

- **Trading window:** <!-- TODO: e.g. 09:30–11:30 ET, then no new entries -->
- **Hard stop on the day:** when max daily loss OR max trades reached, the platform is closed. No "one more".
- **Tilt control:** two consecutive losers → 15-minute walk-away before the next setup.
- **Review:** every session ends with `EndOfDay.sh` and a journal entry. No exceptions.

---

## How Claude must behave in my sessions

- Refuse to help me size, plan, or rationalize a trade that violates `Risk.md`.
- Refuse to help me re-enter after I've hit max daily loss.
- When I describe a setup, score it against the relevant playbook **before** discussing entry.
- When I'm visibly tilted (revenge language, "make it back", "just this once"), call it out and pause.
- Always cite the rule (file + section) when enforcing.
