# Sal — Trading Development Kit

A five-layer Claude Code system for a consistent, rule-based trading operation.
Built from the *Trading Development Kit* spec.

> Write your system once. Stop donating to the market.

---

## The five layers

| Layer | What | Where |
|---|---|---|
| **L1 — Memory** | Always-loaded rules, risk, session behavior | `CLAUDE.md`, `Risk.md` (+ `Risk.local.md`) |
| **L2 — Knowledge** | On-demand setup playbooks | `.claude/skills/{breakout,pullback,mean-reversion}/SKILL.md` |
| **L3 — Guardrails** | Shell scripts around session events | `hooks/{PreMarket,PostTrade,EndOfDay}.sh` |
| **L4 — Delegation** | Specialist subagents (own context window) | `.claude/agents/{market-researcher,risk-manager,journal-analyzer}.md` |
| **L5 — Distribution** | Plugin manifest + action commands | `plugin.json`, `.claude/commands/*.md` |

## First-run checklist

1. **Fill in personal parameters** — search the repo for `<!-- TODO` and `<TODO`. Every placeholder is something only you can answer.
2. **Copy the local risk overrides:** `cp Risk.local.md.example Risk.local.md` and put your account size + broker specifics there. It is gitignored.
3. **Make the hooks executable** (already done in this repo): `chmod +x hooks/*.sh`.
4. **Sanity check:** open a Claude Code session here. The `SessionStart` hook in `.claude/settings.json` runs `PreMarket.sh` automatically and writes `journal/sessions/<today>/premarket.md`.

## Daily flow

```
session opens
   ↓ SessionStart hook runs PreMarket.sh
   ↓ load relevant playbook
   ↓ /enter   → scores setup, calls risk-manager, prepares order
   ↓ /scale   → applies playbook scaling rule
   ↓ /cut     → exits without argument
   ↓ /hedge   → only via risk-manager approval
   ↓ /close   → runs EndOfDay.sh, opens journal, runs journal-analyzer
```

## Starter prompts

From the original spec — paste these into the session as needed:

- **Load full system:** *Load CLAUDE.md, Risk.md, and the breakout playbook. Confirm each rule is active and summarize my current session constraints.*
- **System health check:** *Review all five layers of my trading system. Identify any gaps, conflicts between rules, or missing components.*
- **Session briefing:** *Run PreMarket.sh, load the relevant playbook for today, and give me a one-paragraph briefing on what I should be looking for this session.*
- **Mid-session enforcement:** *Check my current position against Risk.md. Am I within my max position size and daily drawdown limits? Flag any violations immediately.*
- **Debrief:** *Review today's session against my CLAUDE.md rules. Which rules did I follow? Which did I break? Give me three specific corrections for tomorrow.*

## Layout

```
.
├── CLAUDE.md                       # L1
├── Risk.md                         # L1
├── Risk.local.md.example           # L1 (template; .local is gitignored)
├── plugin.json                     # L5 manifest
├── hooks/                          # L3
│   ├── PreMarket.sh
│   ├── PostTrade.sh
│   └── EndOfDay.sh
├── .claude/
│   ├── settings.json               # SessionStart → PreMarket.sh
│   ├── skills/                     # L2 playbooks
│   │   ├── breakout/SKILL.md
│   │   ├── pullback/SKILL.md
│   │   ├── mean-reversion/SKILL.md
│   │   └── find-skills/SKILL.md    # vercel-labs find-skills
│   ├── agents/                     # L4 subagents
│   │   ├── market-researcher.md
│   │   ├── risk-manager.md
│   │   └── journal-analyzer.md
│   └── commands/                   # L5 actions
│       ├── enter.md
│       ├── scale.md
│       ├── cut.md
│       ├── hedge.md
│       └── close.md
└── journal/                        # created by hooks at runtime
    └── sessions/YYYY-MM-DD/
        ├── premarket.md
        └── journal.md
```

## Principle

> Discretion loses, systems win.
> A good setup executed inconsistently is worse than no setup at all — it gives you false data about what works.

Rules in L1. Setups in L2. Discipline enforced in L3. Analysis delegated to L4. Shipped in L5.
