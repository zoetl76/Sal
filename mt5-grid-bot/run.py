#!/usr/bin/env python3
"""Point d'entree du bot grid scalper BTC / MetaTrader 5.

Exemples :
    python run.py --config config.json                 # mode papier (defaut)
    python run.py --config config.json --live          # trading reel
    python run.py --config config.json status          # etat du compte et de la grille
    python run.py --config config.json flatten         # arret d'urgence : tout fermer
    python run.py --config config.json reset           # leve un arret de risque
"""

from __future__ import annotations

import argparse
import sys

from grid_bot.bot import GridBot
from grid_bot.broker import BrokerError
from grid_bot.config import Config, ConfigError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="grid-scalper",
        description="Bot grid scalper BTC pour MetaTrader 5.",
    )
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "status", "flatten", "reset"],
                        help="run (defaut) | status | flatten | reset")
    parser.add_argument("-c", "--config", default="config.json",
                        help="chemin du fichier de configuration JSON")
    parser.add_argument("--live", action="store_true",
                        help="force le trading reel (ecrase dry_run du fichier)")
    parser.add_argument("--paper", action="store_true",
                        help="force le mode papier")
    parser.add_argument("--once", action="store_true",
                        help="n'execute qu'un seul cycle puis sort")
    parser.add_argument("--log-level", default=None,
                        help="DEBUG | INFO | WARNING | ERROR")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        cfg = Config.load(args.config)
    except ConfigError as exc:
        print(f"Configuration invalide : {exc}", file=sys.stderr)
        return 2

    if args.live and args.paper:
        print("--live et --paper sont mutuellement exclusifs.", file=sys.stderr)
        return 2
    if args.live:
        cfg.dry_run = False
    if args.paper:
        cfg.dry_run = True
    if args.log_level:
        cfg.log_level = args.log_level

    if not cfg.dry_run and args.command == "run":
        answer = input(
            f"\n  ATTENTION : trading REEL sur {cfg.symbol} "
            f"(lot {cfg.sizing.lot}, {cfg.grid.levels} paliers/cote).\n"
            "  Tape 'OUI' pour confirmer : "
        ).strip()
        if answer != "OUI":
            print("Annule.")
            return 1

    bot = GridBot(cfg)
    try:
        if args.command == "status":
            return bot.status()
        if args.command == "flatten":
            return bot.flatten()
        if args.command == "reset":
            return bot.reset()
        return bot.run(once=args.once)
    except BrokerError as exc:
        print(f"Erreur courtier : {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
