#!/usr/bin/env python3
"""Backtest du moteur de grille sur donnees historiques.

Sources de bougies :
    --csv data/btc_m5.csv        colonnes : time,open,high,low,close
    --from-mt5                   telecharge l'historique via le terminal MT5 (Windows)
    --synthetic 20000            marche aleatoire, pour verifier la mecanique du bot

Le backtest rejoue exactement le meme `GridEngine` que le mode reel : ce qui est
teste ici est le code qui tradera, pas une reimplementation approchee.

Limites honnetes : execution intra-barre approximee (O -> extreme defavorable ->
extreme favorable -> C), spread constant, pas de swap ni de slippage, pas de
requote ni de gap de week-end. Un resultat de backtest de grille est
systematiquement plus flatteur que le reel.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from grid_bot.broker import Bar, SymbolSpec
from grid_bot.config import Config, ConfigError
from grid_bot.grid import GridEngine
from grid_bot.logger import setup_logger
from grid_bot.sim import SimBroker


# --------------------------------------------------------------------- #
# Chargement des donnees
# --------------------------------------------------------------------- #

def load_csv(path: str) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            keys = {k.strip().lower(): v for k, v in row.items() if k}
            raw_time = keys.get("time") or keys.get("date") or keys.get("timestamp")
            if raw_time is None:
                raise SystemExit("colonne 'time' absente du CSV")
            bars.append(Bar(
                time=parse_time(raw_time),
                open=float(keys["open"]), high=float(keys["high"]),
                low=float(keys["low"]), close=float(keys["close"]),
            ))
    bars.sort(key=lambda b: b.time)
    return bars


def parse_time(value: str) -> datetime:
    value = value.strip()
    if value.isdigit():
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.fromisoformat(value)


def load_mt5(cfg: Config, timeframe: str, count: int) -> list[Bar]:
    from grid_bot.mt5_broker import MT5Broker
    log = setup_logger("backtest.mt5", "INFO", None)
    broker = MT5Broker(cfg, log)
    broker.connect()
    try:
        return broker.rates(timeframe, count)
    finally:
        broker.shutdown()


def synthetic(count: int, start: float = 65_000.0, minutes: int = 5,
              drift_per_bar: float = 0.0, vol_pct: float = 0.0015,
              seed: int = 42) -> list[Bar]:
    """Marche aleatoire log-normale : sert a valider la mecanique, pas la rentabilite."""
    rng = random.Random(seed)
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = start
    bars: list[Bar] = []
    for i in range(count):
        ret = rng.gauss(drift_per_bar, vol_pct)
        close = price * math.exp(ret)
        high = max(price, close) * (1 + abs(rng.gauss(0, vol_pct / 2)))
        low = min(price, close) * (1 - abs(rng.gauss(0, vol_pct / 2)))
        bars.append(Bar(time=t0 + timedelta(minutes=minutes * i),
                        open=price, high=high, low=low, close=close))
        price = close
    return bars


# --------------------------------------------------------------------- #
# Statistiques
# --------------------------------------------------------------------- #

def max_drawdown(curve: list[tuple[datetime, float]]) -> tuple[float, float]:
    peak, max_abs, max_pct = -math.inf, 0.0, 0.0
    for _, equity in curve:
        peak = max(peak, equity)
        dd = peak - equity
        if dd > max_abs:
            max_abs = dd
        if peak > 0 and dd / peak * 100.0 > max_pct:
            max_pct = dd / peak * 100.0
    return max_abs, max_pct


def report(broker: SimBroker, initial: float, bars: list[Bar]) -> dict:
    core = broker.core
    trades = core.closed
    wins = [t for t in trades if t.profit > 0]
    losses = [t for t in trades if t.profit <= 0]
    gross_win = sum(t.profit for t in wins)
    gross_loss = -sum(t.profit for t in losses)
    dd_abs, dd_pct = max_drawdown(core.equity_curve)
    equity = core.equity(broker.tick())
    net = equity - initial

    stats = {
        "bougies": len(bars),
        "periode": f"{bars[0].time:%Y-%m-%d} -> {bars[-1].time:%Y-%m-%d}" if bars else "-",
        "solde_initial": initial,
        "equity_finale": equity,
        "pnl_net": net,
        "pnl_net_pct": net / initial * 100.0 if initial else 0.0,
        "trades": len(trades),
        "gagnants": len(wins),
        "perdants": len(losses),
        "taux_reussite_pct": len(wins) / len(trades) * 100.0 if trades else 0.0,
        "gain_moyen": gross_win / len(wins) if wins else 0.0,
        "perte_moyenne": -gross_loss / len(losses) if losses else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else math.inf,
        "drawdown_max": dd_abs,
        "drawdown_max_pct": dd_pct,
        "positions_ouvertes_fin": len(core.positions),
        "flottant_fin": core.floating(broker.tick()) if broker.tick() else 0.0,
    }
    return stats


def print_report(stats: dict) -> None:
    print("\n" + "=" * 58)
    print("  RESULTAT DU BACKTEST")
    print("=" * 58)
    rows = [
        ("Bougies", f"{stats['bougies']}"),
        ("Periode", stats["periode"]),
        ("Solde initial", f"{stats['solde_initial']:.2f}"),
        ("Equity finale", f"{stats['equity_finale']:.2f}"),
        ("PnL net", f"{stats['pnl_net']:+.2f} ({stats['pnl_net_pct']:+.2f} %)"),
        ("Trades clotures", f"{stats['trades']}"),
        ("Gagnants / perdants", f"{stats['gagnants']} / {stats['perdants']}"),
        ("Taux de reussite", f"{stats['taux_reussite_pct']:.1f} %"),
        ("Gain moyen", f"{stats['gain_moyen']:+.2f}"),
        ("Perte moyenne", f"{stats['perte_moyenne']:+.2f}"),
        ("Profit factor", f"{stats['profit_factor']:.2f}"),
        ("Drawdown max", f"{stats['drawdown_max']:.2f} ({stats['drawdown_max_pct']:.2f} %)"),
        ("Positions restantes", f"{stats['positions_ouvertes_fin']}"),
        ("Flottant final", f"{stats['flottant_fin']:+.2f}"),
    ]
    for label, value in rows:
        print(f"  {label:<22} {value}")
    print("=" * 58 + "\n")


# --------------------------------------------------------------------- #

def build_spec(args: argparse.Namespace, symbol: str) -> SymbolSpec:
    return SymbolSpec(
        name=symbol,
        digits=args.digits,
        point=10 ** -args.digits,
        tick_size=args.tick_size,
        tick_value=args.tick_value,
        contract_size=args.contract_size,
        volume_min=args.volume_min,
        volume_max=100.0,
        volume_step=args.volume_min,
        stops_level=args.stops_level,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backtest du grid scalper BTC.")
    parser.add_argument("-c", "--config", default="config.json")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", help="fichier CSV time,open,high,low,close")
    source.add_argument("--from-mt5", action="store_true", help="historique via le terminal MT5")
    source.add_argument("--synthetic", type=int, metavar="N",
                        help="genere N bougies aleatoires (test de mecanique)")
    parser.add_argument("--timeframe", default="M5", help="unite de temps pour --from-mt5")
    parser.add_argument("--count", type=int, default=50_000, help="nb de bougies pour --from-mt5")
    parser.add_argument("--balance", type=float, default=10_000.0, help="solde initial simule")
    parser.add_argument("--spread", type=float, default=25.0, help="spread constant (USD)")
    parser.add_argument("--commission", type=float, default=0.0,
                        help="commission aller-retour par lot, devise du compte")
    parser.add_argument("--seed", type=int, default=42, help="graine pour --synthetic")
    parser.add_argument("--drift", type=float, default=0.0,
                        help="derive par bougie pour --synthetic (ex 0.0002 = marche haussier)")
    # Specification contractuelle du symbole (a aligner sur ton broker).
    parser.add_argument("--digits", type=int, default=2)
    parser.add_argument("--contract-size", type=float, default=1.0)
    parser.add_argument("--tick-size", type=float, default=0.01)
    parser.add_argument("--tick-value", type=float, default=0.01)
    parser.add_argument("--volume-min", type=float, default=0.01)
    parser.add_argument("--stops-level", type=float, default=0.0)
    parser.add_argument("--equity-csv", help="exporte la courbe d'equity vers ce fichier")
    parser.add_argument("--trades-csv", help="exporte le detail des trades vers ce fichier")
    parser.add_argument("-v", "--verbose", action="store_true", help="journalise chaque decision")
    args = parser.parse_args(argv)

    try:
        cfg = Config.load(args.config)
    except ConfigError as exc:
        print(f"Configuration invalide : {exc}", file=sys.stderr)
        return 2

    cfg.state_file = ""          # aucun etat persiste pendant un backtest
    cfg.log_file = ""
    log = setup_logger("backtest", "DEBUG" if args.verbose else "WARNING", None)

    if args.csv:
        bars = load_csv(args.csv)
    elif args.from_mt5:
        bars = load_mt5(cfg, args.timeframe, args.count)
    else:
        bars = synthetic(args.synthetic, drift_per_bar=args.drift, seed=args.seed)

    if len(bars) < 100:
        print("historique insuffisant (moins de 100 bougies)", file=sys.stderr)
        return 2

    spec = build_spec(args, cfg.symbol)
    broker = SimBroker(spec, bars, balance=args.balance, spread=args.spread,
                       commission_per_lot=args.commission, magic=cfg.magic)
    engine = GridEngine(cfg, broker, log)

    for bar in bars:
        broker.feed(bar)
        engine.cycle()

    stats = report(broker, args.balance, bars)
    print_report(stats)

    if args.equity_csv:
        with open(args.equity_csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["time", "equity"])
            writer.writerows([[t.isoformat(), f"{e:.2f}"] for t, e in broker.core.equity_curve])
        print(f"Courbe d'equity ecrite dans {args.equity_csv}")

    if args.trades_csv:
        with open(args.trades_csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["ouverture", "cloture", "palier", "sens", "volume",
                             "prix_entree", "prix_sortie", "motif", "pnl"])
            for t in broker.core.closed:
                writer.writerow([t.opened_at.isoformat(), t.closed_at.isoformat(),
                                 t.comment, t.side, f"{t.volume:.3f}",
                                 f"{t.price_open:.2f}", f"{t.price_close:.2f}",
                                 t.reason, f"{t.profit:.2f}"])
        print(f"Detail des trades ecrit dans {args.trades_csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
