#!/usr/bin/env python3
"""Compare plusieurs configurations sur un meme jeu de marches simules.

Sert a repondre a une question precise : « ce jeu de parametres est-il
vraiment meilleur que la configuration par defaut, ou juste sur-appris ? »

    python validate.py config.example.json config.optimized.json \
        --seeds 101-112 --bars 10000

Chaque configuration est rejouee sur les memes marches, avec la meme graine :
la comparaison est appariee, pas approximative.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from grid_bot.config import Config, ConfigError
from grid_bot.market import SCENARIOS
from optimize import RunResult, run_backtest


def parse_seeds(spec: str) -> list[int]:
    seeds: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            start, _, end = chunk.partition("-")
            seeds.extend(range(int(start), int(end) + 1))
        elif chunk:
            seeds.append(int(chunk))
    return seeds


def _job(args: tuple) -> tuple[int, RunResult]:
    index, cfg, scenario, seed, bars, balance, spread = args
    return index, run_backtest(cfg, scenario, seed, bars, balance, spread)


def summarise(runs: list[RunResult]) -> dict:
    returns = [r.return_pct for r in runs]
    return {
        "runs": len(runs),
        "moyenne": statistics.fmean(returns),
        "mediane": statistics.median(returns),
        "pire": min(returns),
        "meilleur": max(returns),
        "ecart_type": statistics.pstdev(returns) if len(returns) > 1 else 0.0,
        "pire_dd": max(r.max_dd_pct for r in runs),
        "ruine_pct": sum(1 for r in runs if r.ruined) / len(runs) * 100.0,
        "positifs_pct": sum(1 for r in runs if r.return_pct > 0) / len(runs) * 100.0,
        "trades": sum(r.trades for r in runs),
    }


def per_scenario(runs: list[RunResult]) -> dict[str, tuple[float, float]]:
    grouped: dict[str, list[RunResult]] = {}
    for run in runs:
        grouped.setdefault(run.scenario, []).append(run)
    return {
        name: (statistics.fmean(r.return_pct for r in group),
               sum(1 for r in group if r.ruined) / len(group) * 100.0)
        for name, group in grouped.items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Comparaison appariee de configurations.")
    parser.add_argument("configs", nargs="+", help="fichiers de configuration a comparer")
    parser.add_argument("--seeds", default="101-112", help="graines, ex '1-10' ou '3,7,9'")
    parser.add_argument("--bars", type=int, default=10_000, help="bougies par run")
    parser.add_argument("--scenarios", default="all",
                        help="'all' ou liste separee par des virgules")
    parser.add_argument("--balance", type=float, default=2000.0)
    parser.add_argument("--spread", type=float, default=25.0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    scenarios = SCENARIOS if args.scenarios == "all" else args.scenarios.split(",")
    for scenario in scenarios:
        if scenario not in SCENARIOS:
            print(f"scenario inconnu: {scenario}", file=sys.stderr)
            return 2
    seeds = parse_seeds(args.seeds)

    configs: list[Config] = []
    for path in args.configs:
        try:
            cfg = Config.load(path)
        except ConfigError as exc:
            print(f"{path} : {exc}", file=sys.stderr)
            return 2
        cfg.state_file = ""
        cfg.log_file = ""
        configs.append(cfg)

    jobs = [
        (index, cfg, scenario, seed, args.bars, args.balance, args.spread)
        for index, cfg in enumerate(configs)
        for scenario in scenarios
        for seed in seeds
    ]
    print(f"{len(configs)} configurations x {len(scenarios)} scenarios x {len(seeds)} graines "
          f"x {args.bars} bougies = {len(jobs)} backtests\n")

    results: list[list[RunResult]] = [[] for _ in configs]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, run in pool.map(_job, jobs, chunksize=4):
            results[index].append(run)

    print(f"{'configuration':<26} {'moy':>7} {'med':>7} {'pire':>8} {'meilleur':>9} "
          f"{'ecart':>7} {'ddMax':>7} {'ruine':>7} {'gagn.':>7} {'trades':>7}")
    for path, runs in zip(args.configs, results):
        s = summarise(runs)
        print(f"{Path(path).name:<26} {s['moyenne']:>6.2f}% {s['mediane']:>6.2f}% "
              f"{s['pire']:>7.2f}% {s['meilleur']:>8.2f}% {s['ecart_type']:>6.2f}% "
              f"{s['pire_dd']:>6.2f}% {s['ruine_pct']:>6.1f}% {s['positifs_pct']:>6.1f}% "
              f"{s['trades']:>7d}")

    print(f"\n{'rendement moyen par regime (ruine %)':<38}")
    header = f"{'configuration':<26}" + "".join(f"{s:>16}" for s in scenarios)
    print(header)
    for path, runs in zip(args.configs, results):
        cells = per_scenario(runs)
        line = f"{Path(path).name:<26}"
        for scenario in scenarios:
            mean, ruin = cells.get(scenario, (0.0, 0.0))
            line += f"{mean:>+9.2f}% ({ruin:>2.0f}%)"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
