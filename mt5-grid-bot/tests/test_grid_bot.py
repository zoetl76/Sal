"""Tests unitaires (stdlib uniquement) : python -m unittest discover -s tests -v"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grid_bot.broker import Account, Bar, Position, SymbolSpec, Tick   # noqa: E402
from grid_bot.config import Config, ConfigError                        # noqa: E402
from grid_bot.grid import GridEngine                                   # noqa: E402
from grid_bot.indicators import atr, ema                               # noqa: E402
from grid_bot.risk import RiskManager, in_session                      # noqa: E402
from grid_bot.sim import SimBroker                                     # noqa: E402

SPEC = SymbolSpec(name="BTCUSD", digits=2, point=0.01, tick_size=0.01, tick_value=0.01,
                  contract_size=1.0, volume_min=0.01, volume_max=100.0,
                  volume_step=0.01, stops_level=0.0)

QUIET = logging.getLogger("test")
QUIET.addHandler(logging.NullHandler())
QUIET.propagate = False


def make_config(**overrides) -> Config:
    cfg = Config()
    cfg.state_file = ""
    cfg.log_file = ""
    cfg.symbol = "BTCUSD"
    cfg.grid.step_mode = "fixed"
    cfg.grid.step_fixed = 100.0
    cfg.grid.step_min = 10.0
    cfg.grid.levels = 3
    cfg.sizing.lot = 0.01
    for path, value in overrides.items():
        target = cfg
        *parents, leaf = path.split(".")
        for part in parents:
            target = getattr(target, part)
        setattr(target, leaf, value)
    cfg.validate()
    return cfg


def flat_bars(n: int, price: float = 60_000.0) -> list[Bar]:
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [Bar(time=t0 + timedelta(minutes=i), open=price, high=price,
                low=price, close=price) for i in range(n)]


class TestIndicators(unittest.TestCase):
    def test_atr_needs_history(self):
        self.assertIsNone(atr([1, 2], [0, 1], [1, 2], period=14))

    def test_atr_constant_range(self):
        highs = [110.0] * 30
        lows = [90.0] * 30
        closes = [100.0] * 30
        self.assertAlmostEqual(atr(highs, lows, closes, 14), 20.0, places=6)

    def test_ema_matches_sma_on_flat_series(self):
        self.assertAlmostEqual(ema([5.0] * 50, 10), 5.0, places=9)

    def test_ema_needs_history(self):
        self.assertIsNone(ema([1.0, 2.0], 10))


class TestConfig(unittest.TestCase):
    def test_rejects_unknown_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"symbole": "BTCUSD"}))
            with self.assertRaises(ConfigError):
                Config.load(path)

    def test_rejects_sl_tighter_than_tp(self):
        cfg = Config()
        cfg.grid.tp_mult = 1.0
        cfg.grid.sl_mult = 0.5
        with self.assertRaises(ConfigError):
            cfg.validate()

    def test_risk_sizing_requires_stop_loss(self):
        cfg = Config()
        cfg.sizing.mode = "risk"
        cfg.grid.sl_mult = 0.0
        with self.assertRaises(ConfigError):
            cfg.validate()

    def test_example_config_is_valid(self):
        example = Path(__file__).resolve().parents[1] / "config.example.json"
        self.assertTrue(Config.load(example).symbol)


class TestSymbolSpec(unittest.TestCase):
    def test_volume_normalisation_respects_step_and_bounds(self):
        self.assertAlmostEqual(SPEC.normalize_volume(0.0134), 0.01)
        self.assertAlmostEqual(SPEC.normalize_volume(0.0), 0.01)      # borne basse broker
        self.assertAlmostEqual(SPEC.normalize_volume(1000.0), 100.0)  # borne haute broker

    def test_money_per_price_unit(self):
        # 1 lot = 1 BTC : 1 USD de variation = 1 USD de PnL.
        self.assertAlmostEqual(SPEC.money_per_price_unit(1.0), 1.0)
        self.assertAlmostEqual(SPEC.money_per_price_unit(0.01), 0.01)


class TestGridGeometry(unittest.TestCase):
    def setUp(self):
        cfg = make_config()
        broker = SimBroker(SPEC, flat_bars(10), spread=10.0)
        self.engine = GridEngine(cfg, broker, QUIET)
        self.engine.anchor = 60_000.0
        self.engine.step = 100.0

    def test_levels_are_symmetric_around_anchor(self):
        levels = {lv.key: lv.price for lv in self.engine.levels()}
        self.assertEqual(levels["B1"], 59_900.0)
        self.assertEqual(levels["B3"], 59_700.0)
        self.assertEqual(levels["S1"], 60_100.0)
        self.assertEqual(levels["S3"], 60_300.0)

    def test_take_profit_is_one_step_away(self):
        tp, sl = self.engine._tp_sl_for("buy", 59_900.0)
        self.assertEqual(tp, 60_000.0)
        self.assertEqual(sl, 0.0)
        tp, _ = self.engine._tp_sl_for("sell", 60_100.0)
        self.assertEqual(tp, 60_000.0)

    def test_stop_loss_is_placed_when_configured(self):
        self.engine.cfg.grid.sl_mult = 5.0
        tp, sl = self.engine._tp_sl_for("buy", 59_900.0)
        self.assertEqual(tp, 60_000.0)
        self.assertEqual(sl, 59_400.0)

    def test_limit_orders_never_cross_the_market(self):
        tick = Tick(time=datetime.now(timezone.utc), bid=59_990.0, ask=60_010.0)
        self.assertTrue(self.engine._valid_limit("buy", 59_900.0, tick))
        self.assertFalse(self.engine._valid_limit("buy", 60_050.0, tick))   # au-dessus du ask
        self.assertTrue(self.engine._valid_limit("sell", 60_100.0, tick))
        self.assertFalse(self.engine._valid_limit("sell", 59_900.0, tick))  # sous le bid

    def test_direction_modes(self):
        self.engine.cfg.grid.mode = "long"
        self.assertEqual(self.engine._allowed_sides(), {"buy"})
        self.engine.cfg.grid.mode = "short"
        self.assertEqual(self.engine._allowed_sides(), {"sell"})
        self.engine.cfg.grid.mode = "trend"
        self.engine.trend_bias = "short"
        self.assertEqual(self.engine._allowed_sides(), {"sell"})

    def test_martingale_scales_by_level(self):
        self.engine.cfg.sizing.martingale_factor = 2.0
        self.engine.cfg.sizing.lot_max = 1.0
        self.assertAlmostEqual(self.engine._volume_for(1, 10_000.0), 0.01)
        self.assertAlmostEqual(self.engine._volume_for(3, 10_000.0), 0.04)

    def test_risk_sizing_uses_stop_distance(self):
        self.engine.cfg.sizing.mode = "risk"
        self.engine.cfg.sizing.risk_per_level_pct = 1.0
        self.engine.cfg.sizing.lot_max = 10.0
        self.engine.cfg.grid.sl_mult = 5.0        # 5 * 100 USD = 500 USD de risque par lot
        # 1% de 10 000 = 100 USD risques / 500 USD = 0.2 lot
        self.assertAlmostEqual(self.engine._volume_for(1, 10_000.0), 0.2)


class TestRisk(unittest.TestCase):
    def setUp(self):
        self.cfg = make_config()
        self.now = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)
        self.tick = Tick(time=self.now, bid=59_990.0, ask=60_010.0)

    def _evaluate(self, manager, equity, positions=(), tick=None):
        account = Account(balance=equity, equity=equity, margin=0.0,
                          margin_free=equity, currency="USD")
        return manager.evaluate(account, list(positions), tick or self.tick, SPEC, self.now)

    def test_drawdown_halt_is_terminal(self):
        self.cfg.risk.max_drawdown_pct = 15.0
        self.cfg.risk.daily_loss_pct = 99.0             # on isole le drawdown
        manager = RiskManager(self.cfg)
        self._evaluate(manager, 10_000.0)
        verdict = self._evaluate(manager, 8_400.0)      # -16% > 15%
        self.assertTrue(verdict.halt)
        self.assertEqual(manager.state.halt_kind, "terminal")

    def test_daily_halt_resumes_next_day(self):
        self.cfg.risk.max_drawdown_pct = 99.0
        manager = RiskManager(self.cfg)
        self._evaluate(manager, 10_000.0)
        self.assertTrue(self._evaluate(manager, 9_000.0).halt)   # -10% > 5% quotidien
        self.assertEqual(manager.state.halt_kind, "daily")

        tomorrow = self.now + timedelta(days=1)
        account = Account(balance=9_000.0, equity=9_000.0, margin=0.0,
                          margin_free=9_000.0, currency="USD")
        verdict = manager.evaluate(account, [], self.tick, SPEC, tomorrow)
        self.assertFalse(verdict.halt)

    def test_terminal_halt_survives_the_day_change(self):
        self.cfg.risk.max_drawdown_pct = 15.0
        self.cfg.risk.daily_loss_pct = 99.0
        manager = RiskManager(self.cfg)
        self._evaluate(manager, 10_000.0)
        self._evaluate(manager, 8_000.0)
        tomorrow = self.now + timedelta(days=1)
        account = Account(balance=8_000.0, equity=8_000.0, margin=0.0,
                          margin_free=8_000.0, currency="USD")
        self.assertTrue(manager.evaluate(account, [], self.tick, SPEC, tomorrow).halt)
        manager.reset(8_000.0)
        self.assertFalse(manager.evaluate(account, [], self.tick, SPEC, tomorrow).halt)

    def test_wide_spread_blocks_new_orders_without_halting(self):
        manager = RiskManager(self.cfg)
        wide = Tick(time=self.now, bid=59_900.0, ask=60_100.0)   # spread 200 > 60
        verdict = self._evaluate(manager, 10_000.0, tick=wide)
        self.assertFalse(verdict.halt)
        self.assertFalse(verdict.can_open)

    def test_max_positions_blocks_new_orders(self):
        self.cfg.risk.max_positions = 2
        manager = RiskManager(self.cfg)
        positions = [Position(ticket=i, side="buy", volume=0.01, price_open=60_000.0)
                     for i in range(2)]
        verdict = self._evaluate(manager, 10_000.0, positions=positions)
        self.assertFalse(verdict.can_open)

    def test_basket_take_profit(self):
        self.cfg.risk.basket_tp_currency = 50.0
        manager = RiskManager(self.cfg)
        positions = [Position(ticket=1, side="buy", volume=0.01,
                              price_open=60_000.0, profit=75.0)]
        verdict = self._evaluate(manager, 10_075.0, positions=positions)
        self.assertTrue(verdict.take_basket_profit)

    def test_session_windows(self):
        cfg = make_config()
        cfg.session.enabled = True
        cfg.session.windows = ["22:00-04:00"]           # fenetre a cheval sur minuit
        self.assertTrue(in_session(cfg, self.now.replace(hour=23)))
        self.assertTrue(in_session(cfg, self.now.replace(hour=2)))
        self.assertFalse(in_session(cfg, self.now.replace(hour=12)))

    def test_weekend_filter(self):
        cfg = make_config()
        cfg.session.enabled = True
        cfg.session.trade_weekend = False
        saturday = datetime(2024, 5, 4, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(in_session(cfg, saturday))


class TestSimulationRoundTrip(unittest.TestCase):
    """La grille doit encaisser un pas de gain a chaque aller-retour du prix."""

    def test_buy_level_fills_then_takes_profit(self):
        cfg = make_config(**{"grid.levels": 1, "grid.rearm_cooldown_sec": 0})
        prices = [60_000.0] * 3 + [59_880.0] * 3 + [60_020.0] * 3
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        bars = [Bar(time=t0 + timedelta(minutes=i), open=p, high=p, low=p, close=p)
                for i, p in enumerate(prices)]
        broker = SimBroker(SPEC, bars, balance=10_000.0, spread=10.0, magic=cfg.magic)
        engine = GridEngine(cfg, broker, QUIET)

        for bar in bars:
            broker.feed(bar)
            engine.cycle()

        closed = broker.core.closed
        self.assertGreaterEqual(len(closed), 1)
        trade = closed[0]
        self.assertEqual(trade.side, "buy")
        self.assertEqual(trade.reason, "tp")
        self.assertAlmostEqual(trade.price_close - trade.price_open, cfg.grid.step_fixed)
        self.assertGreater(broker.core.balance, 10_000.0)

    def test_engine_never_exceeds_max_positions(self):
        cfg = make_config(**{"grid.levels": 20, "risk.max_positions": 4,
                             "risk.max_total_lots": 99.0, "risk.max_net_lots": 99.0})
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        bars, price = [], 60_000.0
        for i in range(200):                       # baisse reguliere : tout le cote achat se remplit
            price -= 20.0
            bars.append(Bar(time=t0 + timedelta(minutes=i), open=price + 20, high=price + 20,
                            low=price, close=price))
        broker = SimBroker(SPEC, bars, balance=1_000_000.0, spread=10.0, magic=cfg.magic)
        engine = GridEngine(cfg, broker, QUIET)
        peak = 0
        for bar in bars:
            broker.feed(bar)
            engine.cycle()
            peak = max(peak, len(broker.positions()))
        self.assertLessEqual(peak, cfg.risk.max_positions)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestTimeStop(unittest.TestCase):
    """Le stop temporel borne l'accumulation en tendance."""

    def _run(self, max_age_sec: int) -> tuple[int, float, float]:
        cfg = make_config(**{
            "grid.levels": 6, "grid.rearm_cooldown_sec": 0,
            "grid.max_position_age_sec": max_age_sec,
            "risk.max_positions": 6, "risk.max_total_lots": 9.0,
            "risk.max_net_lots": 9.0, "risk.max_drawdown_pct": 99.0,
            "risk.daily_loss_pct": 99.0,
        })
        t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        bars, price = [], 60_000.0
        for i in range(400):                       # baisse continue : le pire cas
            price -= 15.0
            bars.append(Bar(time=t0 + timedelta(minutes=i), open=price + 15,
                            high=price + 15, low=price, close=price))
        broker = SimBroker(SPEC, bars, balance=100_000.0, spread=10.0, magic=cfg.magic)
        engine = GridEngine(cfg, broker, QUIET)
        worst_floating = 0.0
        for bar in bars:
            broker.feed(bar)
            engine.cycle()
            worst_floating = min(worst_floating, broker.core.floating(broker.tick()))
        return len(broker.core.closed), worst_floating, broker.core.equity(broker.tick())

    def test_time_stop_closes_stale_positions(self):
        trades_without, _, _ = self._run(0)
        trades_with, _, _ = self._run(30 * 60)
        self.assertGreater(trades_with, trades_without,
                           "le stop temporel doit produire des clotures supplementaires")

    def test_time_stop_limits_floating_loss(self):
        _, worst_without, _ = self._run(0)
        _, worst_with, _ = self._run(30 * 60)
        self.assertGreater(worst_with, worst_without,
                           "le flottant au pire moment doit etre moins negatif")

    def test_disabled_by_default(self):
        self.assertEqual(Config().grid.max_position_age_sec, 0)

    def test_negative_age_is_rejected(self):
        cfg = Config()
        cfg.grid.max_position_age_sec = -1
        with self.assertRaises(ConfigError):
            cfg.validate()
