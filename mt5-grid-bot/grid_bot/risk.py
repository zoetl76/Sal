"""Garde-fous. Une grille sans limite de perte finit toujours par tout rendre."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime

from .broker import Account, Position, SymbolSpec, Tick
from .config import Config


@dataclass
class RiskState:
    peak_equity: float = 0.0
    day: str = ""                 # date UTC courante, format ISO
    day_start_equity: float = 0.0
    halted: bool = False
    halt_reason: str = ""
    halt_day: str = ""
    halt_kind: str = ""           # "daily" (reprise le lendemain) | "terminal" (reset manuel)

    def to_dict(self) -> dict:
        return {
            "peak_equity": self.peak_equity,
            "day": self.day,
            "day_start_equity": self.day_start_equity,
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "halt_day": self.halt_day,
            "halt_kind": self.halt_kind,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "RiskState":
        return cls(**{k: raw[k] for k in raw if k in cls.__annotations__})


@dataclass
class RiskVerdict:
    halt: bool = False
    halt_reason: str = ""
    take_basket_profit: bool = False
    blockers: list[str] = field(default_factory=list)

    @property
    def can_open(self) -> bool:
        return not self.halt and not self.blockers


def _parse_window(window: str) -> tuple[dtime, dtime]:
    start_s, _, end_s = window.partition("-")
    def _p(value: str) -> dtime:
        hh, _, mm = value.strip().partition(":")
        return dtime(int(hh), int(mm or 0))
    return _p(start_s), _p(end_s)


def in_session(cfg: Config, now: datetime) -> bool:
    session = cfg.session
    if not session.enabled:
        return True
    if not session.trade_weekend and now.weekday() >= 5:
        return False
    current = now.time()
    for window in session.windows:
        start, end = _parse_window(window)
        if start <= end:
            if start <= current <= end:
                return True
        elif current >= start or current <= end:   # fenetre a cheval sur minuit
            return True
    return False


class RiskManager:
    def __init__(self, cfg: Config, state: RiskState | None = None) -> None:
        self.cfg = cfg
        self.state = state or RiskState()

    # ------------------------------------------------------------------ #

    def evaluate(self, account: Account, positions: list[Position], tick: Tick,
                 spec: SymbolSpec, now: datetime) -> RiskVerdict:
        r = self.cfg.risk
        st = self.state
        verdict = RiskVerdict()

        today = now.date().isoformat()
        if st.day != today:
            st.day = today
            st.day_start_equity = account.equity
            # Seul un arret journalier se leve tout seul : un drawdown maximal
            # ou un appel de marge exige une reprise en main manuelle (`reset`).
            if (st.halted and st.halt_kind == "daily" and r.resume_next_day
                    and st.halt_day != today):
                st.halted, st.halt_reason, st.halt_kind = False, "", ""
        if account.equity > st.peak_equity:
            st.peak_equity = account.equity
        if st.day_start_equity <= 0:
            st.day_start_equity = account.equity

        if st.halted:
            return RiskVerdict(halt=True, halt_reason=f"[{st.halt_kind}] {st.halt_reason}")

        floating = sum(p.profit for p in positions)

        # --- conditions d'arret ---------------------------------------- #
        if st.peak_equity > 0:
            dd_pct = (st.peak_equity - account.equity) / st.peak_equity * 100.0
            if dd_pct >= r.max_drawdown_pct:
                return self._halt(now, f"drawdown {dd_pct:.2f}% >= {r.max_drawdown_pct}%",
                                  "terminal")

        if st.day_start_equity > 0:
            day_pct = (st.day_start_equity - account.equity) / st.day_start_equity * 100.0
            if day_pct >= r.daily_loss_pct:
                return self._halt(now, f"perte du jour {day_pct:.2f}% >= {r.daily_loss_pct}%",
                                  "daily")

        if r.basket_sl_currency > 0 and floating <= -abs(r.basket_sl_currency):
            return self._halt(now, f"basket SL atteint ({floating:.2f})", "daily")

        if account.equity > 0 and account.margin > 0:
            free_pct = account.margin_free / account.equity * 100.0
            if free_pct < r.min_free_margin_pct:
                return self._halt(now, f"marge libre {free_pct:.1f}% < {r.min_free_margin_pct}%",
                                  "terminal")

        # --- prise de benefice globale --------------------------------- #
        if r.basket_tp_currency > 0 and positions and floating >= r.basket_tp_currency:
            verdict.take_basket_profit = True

        # --- blocages temporaires (n'arretent pas le bot) --------------- #
        if not in_session(self.cfg, now):
            verdict.blockers.append("hors session")
        if len(positions) >= r.max_positions:
            verdict.blockers.append(f"max_positions ({r.max_positions}) atteint")

        buy_lots = sum(p.volume for p in positions if p.side == "buy")
        sell_lots = sum(p.volume for p in positions if p.side == "sell")
        if buy_lots + sell_lots >= r.max_total_lots:
            verdict.blockers.append(f"exposition brute {buy_lots + sell_lots:.2f} lots")
        if abs(buy_lots - sell_lots) >= r.max_net_lots:
            verdict.blockers.append(f"exposition nette {abs(buy_lots - sell_lots):.2f} lots")

        if tick.spread > r.max_spread:
            verdict.blockers.append(f"spread {tick.spread:.2f} > {r.max_spread}")

        return verdict

    def _halt(self, now: datetime, reason: str, kind: str) -> RiskVerdict:
        self.state.halted = True
        self.state.halt_reason = reason
        self.state.halt_kind = kind
        self.state.halt_day = now.date().isoformat()
        return RiskVerdict(halt=True, halt_reason=f"[{kind}] {reason}")

    def reset(self, equity: float) -> None:
        """Leve un arret et repart du niveau d'equity courant."""
        self.state.halted = False
        self.state.halt_reason = ""
        self.state.halt_kind = ""
        self.state.peak_equity = equity
        self.state.day_start_equity = equity
