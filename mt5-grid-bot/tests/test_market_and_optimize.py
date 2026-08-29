"""Tests du generateur de marche et de l'optimiseur."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import optimize                                                # noqa: E402
from grid_bot.config import Config                             # noqa: E402
from grid_bot.market import SCENARIOS, describe, generate      # noqa: E402


class TestMarketGenerator(unittest.TestCase):
    def test_scenarios_are_reproducible(self):
        a = generate("mixed", 500, seed=11)
        b = generate("mixed", 500, seed=11)
        self.assertEqual([bar.close for bar in a], [bar.close for bar in b])
        c = generate("mixed", 500, seed=12)
        self.assertNotEqual([bar.close for bar in a], [bar.close for bar in c])

    def test_ohlc_is_coherent(self):
        for scenario in SCENARIOS:
            for bar in generate(scenario, 400, seed=5):
                self.assertGreaterEqual(bar.high, max(bar.open, bar.close))
                self.assertLessEqual(bar.low, min(bar.open, bar.close))
                self.assertGreater(bar.low, 0.0)

    def test_volatility_stays_in_a_plausible_band(self):
        """Le GARCH ne doit ni s'eteindre ni exploser sur aucun scenario."""
        for scenario in SCENARIOS:
            stats = describe(generate(scenario, 4000, seed=3))
            self.assertGreater(stats["vol_annualisee_pct"], 15.0, scenario)
            self.assertLess(stats["vol_annualisee_pct"], 250.0, scenario)

    def test_fat_tails_are_present(self):
        # Une gaussienne a un kurtosis de 3 ; le BTC est nettement au-dessus.
        self.assertGreater(describe(generate("mixed", 6000, seed=9))["kurtosis"], 4.0)

    def test_trend_scenarios_go_the_right_way(self):
        bull = [describe(generate("bull", 4000, seed=s))["variation_pct"] for s in range(1, 6)]
        bear = [describe(generate("bear", 4000, seed=s))["variation_pct"] for s in range(1, 6)]
        self.assertGreater(sum(bull) / len(bull), 10.0)
        self.assertLess(sum(bear) / len(bear), -5.0)

    def test_unknown_scenario_is_rejected(self):
        with self.assertRaises(ValueError):
            generate("lune", 100)


class TestOptimizerParameters(unittest.TestCase):
    def test_every_random_candidate_is_a_valid_config(self):
        import random
        rng = random.Random(0)
        for _ in range(300):
            optimize.apply_params(Config(), optimize.random_params(rng))

    def test_neighbours_stay_valid_and_differ(self):
        import random
        rng = random.Random(1)
        base = optimize.random_params(rng)
        for candidate in optimize.neighbours(base, rng, 40):
            optimize.apply_params(Config(), candidate)
            self.assertNotEqual(candidate, base)

    def test_risk_budget_is_identical_for_every_candidate(self):
        """L'optimiseur cherche du rendement a risque constant, pas du levier."""
        import random
        rng = random.Random(2)
        for _ in range(50):
            cfg = optimize.apply_params(Config(), optimize.random_params(rng))
            self.assertEqual(cfg.risk.max_drawdown_pct, 15.0)
            self.assertEqual(cfg.risk.daily_loss_pct, 5.0)
            self.assertEqual(cfg.sizing.lot, 0.01)

    def test_exposure_caps_follow_grid_size(self):
        params = {"risk.max_positions": 10, "_net_ratio": 0.7}
        cfg = optimize.apply_params(Config(), params)
        self.assertAlmostEqual(cfg.risk.max_total_lots, 0.105)
        self.assertAlmostEqual(cfg.risk.max_net_lots, 0.07)

    def test_score_penalises_ruin_and_drawdown(self):
        safe = optimize.Score(params={}, runs=[
            optimize.RunResult("range", 1, 6.0, 4.0, 100, False),
            optimize.RunResult("bull", 1, 4.0, 5.0, 100, False),
        ])
        risky = optimize.Score(params={}, runs=[
            optimize.RunResult("range", 1, 30.0, 40.0, 100, True),
            optimize.RunResult("bull", 1, -20.0, 45.0, 100, True),
        ])
        self.assertGreater(safe.value, risky.value)
        self.assertEqual(risky.ruin_rate, 1.0)
        self.assertEqual(safe.ruin_rate, 0.0)

    def test_score_prefers_consistency_over_one_lucky_regime(self):
        steady = optimize.Score(params={}, runs=[
            optimize.RunResult("range", 1, 5.0, 6.0, 50, False),
            optimize.RunResult("bear", 1, 4.0, 6.0, 50, False),
        ])
        lucky = optimize.Score(params={}, runs=[
            optimize.RunResult("range", 1, 20.0, 5.0, 50, False),
            optimize.RunResult("bear", 1, -11.0, 25.0, 50, False),
        ])
        self.assertAlmostEqual(steady.mean_return, 4.5)
        self.assertAlmostEqual(lucky.mean_return, 4.5)
        self.assertGreater(steady.value, lucky.value)   # le pire drawdown tranche


if __name__ == "__main__":
    unittest.main(verbosity=2)
