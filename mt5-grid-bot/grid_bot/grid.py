"""Moteur de grille : calcul des paliers, armement, TP, re-centrage."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .broker import Broker, PendingOrder, Position, SymbolSpec, Tick
from .config import Config
from .indicators import atr, ema
from .risk import RiskManager, RiskState, RiskVerdict

STEP_CHANGE_THRESHOLD = 0.15      # on ne recalcule le pas qu'au-dela de 15% d'ecart
REPRICE_TOLERANCE = 0.20          # on repositionne un ordre au-dela de 20% du pas
INDICATOR_REFRESH_SEC = 30.0
HEARTBEAT_SEC = 60.0
HALT_REMINDER_SEC = 900.0


@dataclass
class Level:
    key: str          # "B3" / "S2"
    side: str         # "buy" / "sell"
    index: int        # 1..levels
    price: float


class GridEngine:
    def __init__(self, cfg: Config, broker: Broker, logger: logging.Logger) -> None:
        self.cfg = cfg
        self.broker = broker
        self.log = logger
        self.spec: SymbolSpec = broker.symbol_spec()

        self.anchor: float | None = None
        self.step: float = cfg.grid.step_fixed
        self.cooldowns: dict[str, datetime] = {}
        self.trend_bias: str = "both"

        self._occupied_prev: set[str] = set()
        self._skip_cooldown: set[str] = set()
        self._last_indicator_refresh: datetime | None = None
        self._last_heartbeat: datetime | None = None
        self._halt_logged: datetime | None = None

        self.risk = RiskManager(cfg, self._load_state())

    # ------------------------------------------------------------------ #
    # Etat persistant
    # ------------------------------------------------------------------ #

    @property
    def _state_path(self) -> Path:
        return Path(self.cfg.state_file)

    def _load_state(self) -> RiskState:
        if not self.cfg.state_file:
            return RiskState()
        path = self._state_path
        if not path.exists():
            return RiskState()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.log.warning("etat illisible (%s), redemarrage a vide", exc)
            return RiskState()
        self.anchor = raw.get("anchor")
        self.step = raw.get("step", self.step)
        self.cooldowns = {
            k: datetime.fromisoformat(v) for k, v in raw.get("cooldowns", {}).items()
        }
        self.log.info("Etat recharge depuis %s (ancre=%s, pas=%.2f)",
                      path, self.anchor, self.step)
        return RiskState.from_dict(raw.get("risk", {}))

    def save_state(self) -> None:
        if not self.cfg.state_file:
            return
        path = self._state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "anchor": self.anchor,
            "step": self.step,
            "cooldowns": {k: v.isoformat() for k, v in self.cooldowns.items()},
            "risk": self.risk.state.to_dict(),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ------------------------------------------------------------------ #
    # Boucle
    # ------------------------------------------------------------------ #

    def cycle(self) -> None:
        tick = self.broker.tick()
        if tick is None:
            self.log.debug("pas de cotation disponible")
            return

        account = self.broker.account()
        positions = self.broker.positions()
        orders = self.broker.orders()
        now = self.broker.now()

        verdict = self.risk.evaluate(account, positions, tick, self.spec, now)

        if verdict.halt:
            self._handle_halt(verdict, positions, orders, now)
            return
        self._halt_logged = None

        if verdict.take_basket_profit:
            floating = sum(p.profit for p in positions)
            self.log.info("Basket TP atteint (%+.2f) -> cloture globale", floating)
            self.flatten(positions, orders)
            self.anchor = None
            self.save_state()
            return

        self._refresh_indicators(now)
        self._track_cooldowns(positions, orders, now)
        self._update_anchor(tick, positions, orders)
        self._ensure_take_profits(positions)

        if verdict.can_open:
            self._reprice_orders(orders, tick)
            self._arm_levels(tick, positions, orders, account)
        elif verdict.blockers:
            self.log.debug("ouverture bloquee: %s", "; ".join(verdict.blockers))

        self._heartbeat(now, tick, account, positions, orders, verdict)

    # ------------------------------------------------------------------ #
    # Indicateurs
    # ------------------------------------------------------------------ #

    def _refresh_indicators(self, now: datetime) -> None:
        last = self._last_indicator_refresh
        if last and (now - last).total_seconds() < INDICATOR_REFRESH_SEC:
            return
        self._last_indicator_refresh = now
        self._refresh_step()
        self._refresh_trend()

    def _refresh_step(self) -> None:
        g = self.cfg.grid
        if g.step_mode == "fixed":
            self.step = max(g.step_min, min(g.step_max, g.step_fixed))
            return
        bars = self.broker.rates(g.atr_timeframe, g.atr_period * 4 + 10)
        value = atr([b.high for b in bars], [b.low for b in bars],
                    [b.close for b in bars], g.atr_period)
        if value is None:
            if self.step <= 0:
                self.step = max(g.step_min, min(g.step_max, g.step_fixed))
            return
        target = max(g.step_min, min(g.step_max, value * g.atr_mult))
        if self.step <= 0 or abs(target - self.step) / self.step > STEP_CHANGE_THRESHOLD:
            self.log.info("Pas de grille : %.2f -> %.2f (ATR %s = %.2f)",
                          self.step, target, g.atr_timeframe, value)
            self.step = target

    def _refresh_trend(self) -> None:
        if not self.cfg.trend.enabled:
            self.trend_bias = "both"
            return
        t = self.cfg.trend
        bars = self.broker.rates(t.timeframe, t.ema_slow + 50)
        closes = [b.close for b in bars]
        fast, slow = ema(closes, t.ema_fast), ema(closes, t.ema_slow)
        if fast is None or slow is None:
            self.trend_bias = "both"
            return
        bias = "long" if fast > slow else "short"
        if bias != self.trend_bias:
            self.log.info("Biais de tendance : %s (EMA%d=%.2f vs EMA%d=%.2f)",
                          bias, t.ema_fast, fast, t.ema_slow, slow)
        self.trend_bias = bias

    # ------------------------------------------------------------------ #
    # Paliers
    # ------------------------------------------------------------------ #

    def levels(self) -> list[Level]:
        if self.anchor is None or self.step <= 0:
            return []
        out: list[Level] = []
        for i in range(1, self.cfg.grid.levels + 1):
            out.append(Level(f"B{i}", "buy", i, self.anchor - i * self.step))
            out.append(Level(f"S{i}", "sell", i, self.anchor + i * self.step))
        return out

    def _allowed_sides(self) -> set[str]:
        mode = self.cfg.grid.mode
        if mode == "long":
            return {"buy"}
        if mode == "short":
            return {"sell"}
        if mode == "trend":
            if self.trend_bias == "long":
                return {"buy"}
            if self.trend_bias == "short":
                return {"sell"}
        return {"buy", "sell"}

    def _key_of(self, comment: str) -> str | None:
        tag = self.cfg.tag
        if not comment.startswith(tag):
            return None
        key = comment[len(tag):].strip()
        return key or None

    def _nearest_level(self, side: str, price: float) -> str | None:
        """Rattache un ordre/une position au palier le plus proche.

        Filet pour les brokers qui tronquent ou effacent le commentaire, et pour
        le slippage d'execution : sans ca le palier serait vu comme libre et
        re-arme, ce qui doublerait l'exposition.
        """
        tolerance = self.step * 0.4
        best_key, best_gap = None, tolerance
        for level in self.levels():
            if level.side != side:
                continue
            gap = abs(level.price - price)
            if gap <= best_gap:
                best_key, best_gap = level.key, gap
        return best_key

    def _occupied(self, positions: list[Position],
                  orders: list[PendingOrder]) -> dict[str, str]:
        """key -> "position" | "order"."""
        occupied: dict[str, str] = {}
        for o in orders:
            key = self._key_of(o.comment) or self._nearest_level(o.side, o.price)
            if key:
                occupied[key] = "order"
        for p in positions:
            key = self._key_of(p.comment) or self._nearest_level(p.side, p.price_open)
            if key:
                occupied[key] = "position"
        return occupied

    def _track_cooldowns(self, positions: list[Position], orders: list[PendingOrder],
                         now: datetime) -> None:
        occupied = set(self._occupied(positions, orders))
        closed = (self._occupied_prev - occupied) - self._skip_cooldown
        self._skip_cooldown.clear()
        if closed:
            until = now + timedelta(seconds=self.cfg.grid.rearm_cooldown_sec)
            for key in closed:
                self.cooldowns[key] = until
            self.log.info("Paliers liberes: %s (re-armement dans %ds)",
                          ", ".join(sorted(closed)), self.cfg.grid.rearm_cooldown_sec)
        self._occupied_prev = occupied
        self.cooldowns = {k: v for k, v in self.cooldowns.items() if v > now}

    # ------------------------------------------------------------------ #
    # Ancre
    # ------------------------------------------------------------------ #

    def _update_anchor(self, tick: Tick, positions: list[Position],
                       orders: list[PendingOrder]) -> None:
        g = self.cfg.grid
        mid = tick.mid
        if self.anchor is None:
            self.anchor = self.spec.normalize_price(mid)
            self.log.info("Ancre initialisee a %.2f (pas %.2f, %d paliers/cote)",
                          self.anchor, self.step, g.levels)
            return

        span = self.step * g.levels
        drift = mid - self.anchor
        if abs(drift) <= span * g.reanchor_mult:
            return

        if not positions:
            old = self.anchor
            self.anchor = self.spec.normalize_price(mid)
            self.log.info("Re-centrage de la grille : %.2f -> %.2f", old, self.anchor)
            self._cancel_all_orders(orders)
        elif g.trail_grid:
            shift = drift - (span * g.reanchor_mult) * (1 if drift > 0 else -1)
            old = self.anchor
            self.anchor = self.spec.normalize_price(self.anchor + shift)
            self.log.info("Grille suiveuse : ancre %.2f -> %.2f (%d position(s) ouverte(s))",
                          old, self.anchor, len(positions))

    # ------------------------------------------------------------------ #
    # Ordres
    # ------------------------------------------------------------------ #

    def _volume_for(self, index: int, account_equity: float) -> float:
        s = self.cfg.sizing
        if s.mode == "risk":
            sl_distance = self.step * self.cfg.grid.sl_mult
            per_unit = self.spec.money_per_price_unit(1.0)
            if sl_distance <= 0 or per_unit <= 0:
                volume = s.lot
            else:
                volume = (account_equity * s.risk_per_level_pct / 100.0) / (sl_distance * per_unit)
        else:
            volume = s.lot
        volume *= s.martingale_factor ** (index - 1)
        lot_min = max(s.lot_min, self.spec.volume_min)
        volume = max(lot_min, min(s.lot_max, volume))
        return self.spec.normalize_volume(volume)

    def _tp_sl_for(self, side: str, price: float) -> tuple[float, float]:
        g = self.cfg.grid
        tp_distance = self.step * g.tp_mult
        sl_distance = self.step * g.sl_mult if g.sl_mult > 0 else 0.0
        if side == "buy":
            tp = price + tp_distance
            sl = price - sl_distance if sl_distance else 0.0
        else:
            tp = price - tp_distance
            sl = price + sl_distance if sl_distance else 0.0
        return self.spec.normalize_price(tp), (self.spec.normalize_price(sl) if sl else 0.0)

    def _valid_limit(self, side: str, price: float, tick: Tick) -> bool:
        """Un buy-limit doit rester sous le ask, un sell-limit au-dessus du bid."""
        gap = max(self.spec.stops_level, self.spec.point)
        if side == "buy":
            return price <= tick.ask - gap
        return price >= tick.bid + gap

    def _arm_levels(self, tick: Tick, positions: list[Position],
                    orders: list[PendingOrder], account) -> None:
        occupied = self._occupied(positions, orders)
        allowed = self._allowed_sides()
        now = self.broker.now()
        open_slots = self.cfg.risk.max_positions - len(positions) - len(orders)

        for level in self.levels():
            if open_slots <= 0:
                break
            if level.key in occupied or level.side not in allowed:
                continue
            if self.cooldowns.get(level.key, now) > now:
                continue
            price = self.spec.normalize_price(level.price)
            if not self._valid_limit(level.side, price, tick):
                continue
            volume = self._volume_for(level.index, account.equity)
            tp, sl = self._tp_sl_for(level.side, price)
            ticket = self.broker.place_pending(
                level.side, volume, price, tp, sl, f"{self.cfg.tag}{level.key}"
            )
            if ticket:
                open_slots -= 1
                self.log.info("Palier %s arme : %s %.3f @ %.2f (TP %.2f)",
                              level.key, level.side, volume, price, tp)

    def _reprice_orders(self, orders: list[PendingOrder], tick: Tick) -> None:
        """Recale les ordres en attente quand le pas ou l'ancre ont bouge."""
        wanted = {lv.key: lv for lv in self.levels()}
        tolerance = self.step * REPRICE_TOLERANCE
        for order in orders:
            key = self._key_of(order.comment)
            level = wanted.get(key) if key else None
            if level is None:
                self.log.info("Ordre orphelin #%s (%s) -> annulation", order.ticket, order.comment)
                self.broker.cancel_order(order.ticket)
                continue
            target = self.spec.normalize_price(level.price)
            if abs(order.price - target) <= tolerance:
                continue
            if not self._valid_limit(level.side, target, tick):
                continue
            self.log.info("Recalage %s : %.2f -> %.2f", key, order.price, target)
            if self.broker.cancel_order(order.ticket):
                self._skip_cooldown.add(key)

    def _ensure_take_profits(self, positions: list[Position]) -> None:
        """Filet de securite : une position sans TP (rejet broker, restart) est corrigee."""
        for pos in positions:
            tp, sl = self._tp_sl_for(pos.side, pos.price_open)
            needs_tp = not pos.tp
            needs_sl = bool(self.cfg.grid.sl_mult) and not pos.sl
            if needs_tp or needs_sl:
                self.log.info("Position #%s sans TP/SL -> pose TP=%.2f SL=%.2f",
                              pos.ticket, tp, sl)
                self.broker.set_tp_sl(pos, tp, sl or pos.sl)

    def _cancel_all_orders(self, orders: list[PendingOrder]) -> None:
        for order in orders:
            if self.broker.cancel_order(order.ticket):
                key = self._key_of(order.comment)
                if key:
                    self._skip_cooldown.add(key)

    def flatten(self, positions: list[Position], orders: list[PendingOrder]) -> None:
        self._cancel_all_orders(orders)
        for pos in positions:
            self.broker.close_position(pos)
        self._occupied_prev = set()

    # ------------------------------------------------------------------ #

    def _handle_halt(self, verdict: RiskVerdict, positions: list[Position],
                     orders: list[PendingOrder], now: datetime) -> None:
        first = self._halt_logged is None
        if first:
            self.log.error("ARRET RISQUE : %s", verdict.halt_reason)
            if self.cfg.risk.close_all_on_halt and (positions or orders):
                self.log.error("Cloture de %d position(s) et %d ordre(s)",
                               len(positions), len(orders))
                self.flatten(positions, orders)
            self.anchor = None
            self.save_state()
        if first or (now - self._halt_logged).total_seconds() >= HALT_REMINDER_SEC:
            self._halt_logged = now
            if self.risk.state.halt_kind == "terminal":
                self.log.error("Bot en pause : %s. Reprise manuelle avec "
                               "`python run.py --config <cfg> reset`.", verdict.halt_reason)
            else:
                self.log.warning("Bot en pause jusqu'au prochain jour UTC : %s",
                                 verdict.halt_reason)

    def _heartbeat(self, now: datetime, tick: Tick, account, positions: list[Position],
                   orders: list[PendingOrder], verdict: RiskVerdict) -> None:
        last = self._last_heartbeat
        if last and (now - last).total_seconds() < HEARTBEAT_SEC:
            return
        self._last_heartbeat = now
        floating = sum(p.profit for p in positions)
        self.log.info(
            "prix=%.2f spread=%.2f | ancre=%s pas=%.2f | pos=%d ordres=%d "
            "flottant=%+.2f equity=%.2f%s",
            tick.mid, tick.spread,
            f"{self.anchor:.2f}" if self.anchor else "-",
            self.step, len(positions), len(orders), floating, account.equity,
            f" | bloque: {'; '.join(verdict.blockers)}" if verdict.blockers else "",
        )
        self.save_state()
