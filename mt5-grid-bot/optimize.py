#!/usr/bin/env python3
"""Recherche des meilleurs parametres de grille, avec validation hors echantillon.

Methode, en trois etapes :

  1. EXPLORATION  — recherche aleatoire sur un large espace de parametres,
     chaque candidat evalue sur plusieurs regimes de marche (range, haussier,
     baissier, chaotique, mixte) et plusieurs graines.
  2. AFFINAGE     — les meilleurs candidats sont perturbes localement et
     re-evalues sur davantage de scenarios, krach compris.
  3. VALIDATION   — les finalistes sont rejoues sur des graines JAMAIS vues
     pendant les deux premieres etapes. Un jeu de parametres qui s'effondre
     ici etait sur-appris, pas bon.

Le score privilegie la survie, pas le rendement :

    score = rendement_moyen / max(2, pire_drawdown) - 3 x taux_de_ruine

Un candidat qui gagne 30 % dans un range mais explose en tendance est
elimine par le `pire_drawdown` et par le taux de ruine (arrets terminaux).

    python optimize.py --stage all --candidates 200
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from grid_bot.broker import SymbolSpec
from grid_bot.config import Config
from grid_bot.grid import GridEngine
from grid_bot.market import generate
from grid_bot.sim import SimBroker

QUIET = logging.getLogger("optimize")
QUIET.addHandler(logging.NullHandler())
QUIET.propagate = False

# 1 lot = 1 BTC, cotation a 2 decimales, lot minimum 0,01.
SPEC = SymbolSpec(name="BTCUSD", digits=2, point=0.01, tick_size=0.01, tick_value=0.01,
                  contract_size=1.0, volume_min=0.01, volume_max=100.0,
                  volume_step=0.01, stops_level=0.0)

# Espace de recherche large : ce qui change vraiment le comportement d'une grille.
SPACE_LARGE: dict[str, list] = {
    "grid.levels":              [4, 6, 8, 10, 14],
    "grid.atr_mult":            [0.25, 0.4, 0.5, 0.7, 1.0, 1.4],
    "grid.step_min":            [50.0, 80.0, 120.0, 200.0],
    "grid.step_max":            [800.0, 1500.0],
    "grid.tp_mult":             [0.6, 0.8, 1.0, 1.3, 1.8],
    "grid.sl_mult":             [0.0, 8.0, 15.0],
    "grid.mode":                ["both", "trend", "long"],
    "grid.rearm_cooldown_sec":  [0, 60, 300],
    "grid.reanchor_mult":       [0.8, 1.2, 1.5, 2.5],
    "grid.trail_grid":          [False, True],
    "risk.max_positions":       [4, 6, 10, 16],
    "risk.basket_tp_currency":  [0.0, 15.0, 40.0, 100.0],
    "_net_ratio":               [0.4, 0.7, 1.05],   # plafond d'exposition nette
}

# Espace resserre autour de la geometrie qui survit : pas larges, peu de
# positions simultanees, take profit au-dela d'un pas, stop lointain mais reel.
SPACE_FOCUS: dict[str, list] = {
    "grid.levels":              [6, 10, 14, 20],
    "grid.atr_mult":            [0.7, 1.0, 1.4, 2.0],
    "grid.step_min":            [150.0, 200.0, 300.0],
    "grid.step_max":            [800.0, 1500.0],
    "grid.tp_mult":             [1.3, 1.8, 2.5, 3.5],
    "grid.sl_mult":             [5.0, 8.0, 12.0, 20.0],
    "grid.mode":                ["both", "trend"],
    "grid.rearm_cooldown_sec":  [120, 300, 900],
    "grid.reanchor_mult":       [1.0, 1.5, 2.5],
    "grid.trail_grid":          [False, True],
    "risk.max_positions":       [2, 3, 4, 6],
    "risk.basket_tp_currency":  [0.0, 40.0, 100.0],
    "_net_ratio":               [0.25, 0.4, 0.55],
}

SPACES = {"large": SPACE_LARGE, "focus": SPACE_FOCUS}
SPACE: dict[str, list] = SPACE_LARGE     # espace actif, choisi par --space

SCENARIOS_EXPLORE = ["range", "bull", "bear", "chop", "mixed"]
SCENARIOS_FULL = ["range", "bull", "bear", "crash", "chop", "mixed"]


# --------------------------------------------------------------------- #
# Application des parametres
# --------------------------------------------------------------------- #

def apply_params(cfg: Config, params: dict) -> Config:
    cfg = copy.deepcopy(cfg)
    for path, value in params.items():
        if path.startswith("_"):
            continue
        target = cfg
        *parents, leaf = path.split(".")
        for part in parents:
            target = getattr(target, part)
        setattr(target, leaf, value)

    # Budget de risque FIXE, identique pour tous les candidats : on optimise le
    # rendement a risque donne, on n'optimise pas le droit de perdre davantage.
    cfg.sizing.lot = 0.01
    cfg.sizing.lot_max = 0.05
    cfg.risk.max_drawdown_pct = 15.0
    cfg.risk.daily_loss_pct = 5.0
    cfg.risk.max_spread = 60.0

    # Les plafonds d'exposition suivent la taille de la grille : sinon ils
    # bloquent arbitrairement les configurations a nombreux paliers.
    lots = cfg.sizing.lot * cfg.risk.max_positions
    cfg.risk.max_total_lots = round(lots * 1.05, 4)
    cfg.risk.max_net_lots = round(lots * params.get("_net_ratio", 1.05), 4)
    if cfg.grid.mode == "trend":
        cfg.trend.enabled = True
    cfg.state_file = ""
    cfg.log_file = ""
    cfg.dry_run = True
    cfg.validate()
    return cfg


def random_params(rng: random.Random) -> dict:
    params = {key: rng.choice(values) for key, values in SPACE.items()}
    # Contrainte de coherence : un SL doit etre plus loin que le TP.
    if params["grid.sl_mult"] and params["grid.sl_mult"] <= params["grid.tp_mult"]:
        params["grid.sl_mult"] = 0.0
    if params["grid.step_max"] < params["grid.step_min"]:
        params["grid.step_max"] = 1500.0
    return params


def neighbours(params: dict, rng: random.Random, count: int) -> list[dict]:
    """Perturbe un a deux parametres a la fois autour d'un bon candidat."""
    out = []
    keys = list(SPACE)
    for _ in range(count):
        candidate = dict(params)
        for key in rng.sample(keys, rng.choice([1, 1, 2])):
            values = SPACE[key]
            if candidate[key] in values and len(values) > 1:
                index = values.index(candidate[key])
                choices = [i for i in (index - 1, index + 1) if 0 <= i < len(values)]
                candidate[key] = values[rng.choice(choices)]
            else:
                candidate[key] = rng.choice(values)
        if candidate["grid.sl_mult"] and candidate["grid.sl_mult"] <= candidate["grid.tp_mult"]:
            candidate["grid.sl_mult"] = 0.0
        if candidate["grid.step_max"] < candidate["grid.step_min"]:
            candidate["grid.step_max"] = 1500.0
        out.append(candidate)
    return out


# --------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------- #

@dataclass
class RunResult:
    scenario: str
    seed: int
    return_pct: float
    max_dd_pct: float
    trades: int
    ruined: bool


@dataclass
class Score:
    params: dict
    runs: list[RunResult] = field(default_factory=list)

    @property
    def mean_return(self) -> float:
        return statistics.fmean(r.return_pct for r in self.runs) if self.runs else 0.0

    @property
    def worst_return(self) -> float:
        return min((r.return_pct for r in self.runs), default=0.0)

    @property
    def worst_dd(self) -> float:
        return max((r.max_dd_pct for r in self.runs), default=0.0)

    @property
    def ruin_rate(self) -> float:
        return (sum(1 for r in self.runs if r.ruined) / len(self.runs)) if self.runs else 1.0

    @property
    def trades(self) -> int:
        return sum(r.trades for r in self.runs)

    @property
    def value(self) -> float:
        return self.mean_return / max(2.0, self.worst_dd) - 3.0 * self.ruin_rate

    def by_scenario(self) -> dict[str, float]:
        out: dict[str, list[float]] = {}
        for run in self.runs:
            out.setdefault(run.scenario, []).append(run.return_pct)
        return {k: statistics.fmean(v) for k, v in out.items()}


def run_backtest(cfg: Config, scenario: str, seed: int, bars_count: int,
                 balance: float, spread: float) -> RunResult:
    """Un backtest, du meme moteur que le mode reel. Reutilise par validate.py."""
    bars = generate(scenario, bars_count, seed=seed)
    broker = SimBroker(SPEC, bars, balance=balance, spread=spread, magic=cfg.magic)
    engine = GridEngine(cfg, broker, QUIET)

    for bar in bars:
        broker.feed(bar)
        engine.cycle()

    curve = broker.core.equity_curve
    peak, max_dd = -1e18, 0.0
    for _, equity in curve:
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)
    final = broker.core.equity(broker.tick())
    return RunResult(
        scenario=scenario,
        seed=seed,
        return_pct=(final - balance) / balance * 100.0,
        max_dd_pct=max_dd,
        trades=len(broker.core.closed),
        ruined=engine.risk.state.halt_kind == "terminal",
    )


def run_once(job: tuple) -> RunResult:
    params, scenario, seed, bars_count, balance, spread = job
    cfg = apply_params(Config(), params)
    return run_backtest(cfg, scenario, seed, bars_count, balance, spread)


def evaluate(pool: ProcessPoolExecutor, candidates: list[dict], scenarios: list[str],
             seeds: list[int], bars: int, balance: float, spread: float) -> list[Score]:
    jobs, owners = [], []
    for index, params in enumerate(candidates):
        for scenario in scenarios:
            for seed in seeds:
                jobs.append((params, scenario, seed, bars, balance, spread))
                owners.append(index)

    scores = [Score(params=p) for p in candidates]
    for owner, result in zip(owners, pool.map(run_once, jobs, chunksize=4)):
        scores[owner].runs.append(result)
    return scores


# --------------------------------------------------------------------- #
# Affichage
# --------------------------------------------------------------------- #

def describe_params(params: dict) -> str:
    return (f"{params['grid.mode']:5s} L{params['grid.levels']:<2d} "
            f"atr{params['grid.atr_mult']:<4} min{int(params['grid.step_min']):<4d} "
            f"tp{params['grid.tp_mult']:<4} sl{params['grid.sl_mult']:<5} "
            f"pos{params['risk.max_positions']:<3d} "
            f"bTP{int(params['risk.basket_tp_currency']):<4d} "
            f"cd{params['grid.rearm_cooldown_sec']:<4d} "
            f"ra{params['grid.reanchor_mult']:<4} "
            f"{'trail' if params['grid.trail_grid'] else '     '}")


def print_table(title: str, scores: list[Score], limit: int = 15) -> None:
    print(f"\n=== {title} ===")
    print(f"{'#':>3} {'score':>7} {'rend.moy':>9} {'pire':>8} {'ddMax':>7} "
          f"{'ruine':>6} {'trades':>7}  parametres")
    for rank, score in enumerate(scores[:limit], 1):
        print(f"{rank:>3} {score.value:>7.3f} {score.mean_return:>8.2f}% "
              f"{score.worst_return:>7.2f}% {score.worst_dd:>6.2f}% "
              f"{score.ruin_rate * 100:>5.0f}% {score.trades:>7d}  "
              f"{describe_params(score.params)}")


# --------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Optimiseur de parametres du grid scalper.")
    parser.add_argument("--candidates", type=int, default=200, help="candidats explores")
    parser.add_argument("--refine-top", type=int, default=20, help="candidats affines")
    parser.add_argument("--finalists", type=int, default=8, help="finalistes valides")
    parser.add_argument("--bars", type=int, default=6000, help="bougies par run (exploration)")
    parser.add_argument("--bars-final", type=int, default=10000, help="bougies par run (validation)")
    parser.add_argument("--balance", type=float, default=2000.0, help="solde initial simule")
    parser.add_argument("--spread", type=float, default=25.0, help="spread constant (USD)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1, help="graine de la recherche")
    parser.add_argument("--out", default="config.optimized.json",
                        help="fichier de configuration ecrit pour le gagnant")
    parser.add_argument("--space", default="large", choices=sorted(SPACES),
                        help="'large' explore tout, 'focus' resserre autour de la "
                             "geometrie qui survit aux tendances")
    args = parser.parse_args(argv)

    global SPACE
    SPACE = SPACES[args.space]
    print(f"Espace de recherche : {args.space} "
          f"({len(SPACE)} parametres, "
          f"{__import__('math').prod(len(v) for v in SPACE.values()):,} combinaisons)")

    rng = random.Random(args.seed)
    started = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        # --- 1. exploration ------------------------------------------- #
        candidates = [random_params(rng) for _ in range(args.candidates)]
        print(f"[1/3] Exploration : {args.candidates} candidats x "
              f"{len(SCENARIOS_EXPLORE)} scenarios x 2 graines = "
              f"{args.candidates * len(SCENARIOS_EXPLORE) * 2} backtests")
        scores = evaluate(pool, candidates, SCENARIOS_EXPLORE, [1, 2],
                          args.bars, args.balance, args.spread)
        scores.sort(key=lambda s: s.value, reverse=True)
        print_table(f"Exploration ({time.time() - started:.0f} s)", scores)

        # --- 2. affinage ---------------------------------------------- #
        seeds_refine = [1, 2, 3]
        pool_refine: list[dict] = []
        for score in scores[:args.refine_top]:
            pool_refine.append(score.params)
            pool_refine.extend(neighbours(score.params, rng, 4))
        print(f"\n[2/3] Affinage : {len(pool_refine)} candidats x "
              f"{len(SCENARIOS_FULL)} scenarios x {len(seeds_refine)} graines = "
              f"{len(pool_refine) * len(SCENARIOS_FULL) * len(seeds_refine)} backtests")
        refined = evaluate(pool, pool_refine, SCENARIOS_FULL, seeds_refine,
                           args.bars, args.balance, args.spread)
        refined.sort(key=lambda s: s.value, reverse=True)
        print_table(f"Affinage ({time.time() - started:.0f} s)", refined)

        # --- 3. validation hors echantillon --------------------------- #
        seeds_oos = list(range(101, 113))
        finalists = [s.params for s in refined[:args.finalists]]
        print(f"\n[3/3] Validation hors echantillon : {len(finalists)} finalistes x "
              f"{len(SCENARIOS_FULL)} scenarios x {len(seeds_oos)} graines inedites = "
              f"{len(finalists) * len(SCENARIOS_FULL) * len(seeds_oos)} backtests")
        validated = evaluate(pool, finalists, SCENARIOS_FULL, seeds_oos,
                             args.bars_final, args.balance, args.spread)
        validated.sort(key=lambda s: s.value, reverse=True)
        print_table(f"Validation hors echantillon ({time.time() - started:.0f} s)", validated)

    if not validated:
        print("Aucun candidat valide.", file=sys.stderr)
        return 1

    best = validated[0]
    print("\n=== Gagnant : rendement moyen par regime (hors echantillon) ===")
    for scenario, mean in sorted(best.by_scenario().items()):
        print(f"  {scenario:8s} {mean:+7.2f} %")

    cfg = apply_params(Config(), best.params)
    cfg.state_file = "state/grid_state.json"
    cfg.log_file = "logs/grid_bot.log"
    payload = cfg.to_dict()
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    print(f"\nConfiguration gagnante ecrite dans {args.out}")
    print(f"Duree totale : {time.time() - started:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
