#!/usr/bin/env python3
"""
SAL — Agent de trading S&P 500 propulsé par Claude.

Usage:
  python main.py trade               # Mode trading en direct (1 décision)
  python main.py backtest            # Backtest sur 1 an (rule-based)
  python main.py backtest --start 2022-01-01 --end 2023-12-31
  python main.py snapshot            # Affiche les données de marché actuelles
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

load_dotenv()

console = Console()


def cmd_snapshot(args):
    from src.data import get_market_data, get_latest_snapshot
    from src.signals import compute_all_signals, score_signals

    console.print("[bold cyan]Récupération des données S&P 500...[/]")
    df = get_market_data()
    snap = get_latest_snapshot(df)
    signals = compute_all_signals(snap)
    score = score_signals(signals)

    # Tableau des données de marché
    t = Table(title=f"SPY — {snap['date']}", box=box.ROUNDED, show_header=True)
    t.add_column("Indicateur", style="cyan")
    t.add_column("Valeur", justify="right")
    t.add_row("Prix", f"[bold]{snap['close']:.2f}$[/]")
    t.add_row("Variation 1j", f"[{'green' if snap['return_1d'] >= 0 else 'red'}]{snap['return_1d']:+.2f}%[/]")
    t.add_row("Variation 5j", f"[{'green' if snap['return_5d'] >= 0 else 'red'}]{snap['return_5d']:+.2f}%[/]")
    t.add_row("RSI(14)", f"{snap['rsi']:.1f}")
    t.add_row("MACD hist", f"{snap['macd_hist']:+.4f}")
    t.add_row("Bollinger %", f"{snap['bb_pct']:.0%}")
    t.add_row("SMA50 / SMA200", f"{snap['sma_50']:.2f} / {snap['sma_200']:.2f}")
    t.add_row("ATR(14)", f"{snap['atr']:.2f}$")
    t.add_row("Volume ratio", f"{snap['vol_ratio']:.2f}x")
    console.print(t)

    # Signaux
    console.print()
    st = Table(title="Signaux techniques", box=box.SIMPLE)
    st.add_column("Indicateur", style="cyan")
    st.add_column("Direction", justify="center")
    st.add_column("Force", justify="center")
    st.add_column("Message")
    for s in signals:
        color = "green" if s.direction == "BULLISH" else ("red" if s.direction == "BEARISH" else "yellow")
        st.add_row(s.name, f"[{color}]{s.direction}[/]", s.strength, s.description)
    console.print(st)

    bias_color = "green" if "HAUSSIER" in score["biais"] else ("red" if "BAISSIER" in score["biais"] else "yellow")
    console.print(Panel(
        f"Bull: {score['bull_score']} | Bear: {score['bear_score']} | Net: {score['net_score']:+.2f}/10\n"
        f"[bold {bias_color}]Biais: {score['biais']}[/]",
        title="Score global", border_style=bias_color
    ))


def cmd_trade(args):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[bold red]Erreur: ANTHROPIC_API_KEY manquant dans l'environnement.[/]")
        sys.exit(1)

    from src.data import get_market_data, get_latest_snapshot
    from src.agent import TradingAgent
    from src.portfolio import Portfolio
    from config.settings import INITIAL_CAPITAL

    console.print("[bold cyan]SAL — Agent de trading S&P 500[/]")
    console.print("[dim]Récupération des données...[/]")

    df = get_market_data()
    snap = get_latest_snapshot(df)
    portfolio = Portfolio(INITIAL_CAPITAL)

    console.print(f"[dim]Analyse en cours avec Claude ({args.model})...[/]\n")
    agent = TradingAgent(api_key=api_key, model=args.model)
    decision = agent.decide(snap, portfolio)

    action = decision["action"]
    action_color = "green" if action == "BUY" else ("red" if action == "SELL" else "yellow")
    conviction = decision.get("conviction", "?")
    stars = "★" * int(conviction) + "☆" * (10 - int(conviction))

    console.print(Panel(
        f"[bold {action_color}]ACTION: {action}[/]\n"
        f"Conviction: {stars} ({conviction}/10)\n\n"
        f"[italic]{decision.get('raison', '')}[/]\n\n"
        f"[dim]Risque principal: {decision.get('risques', 'N/A')}[/]"
        + (f"\n[dim]Capital à engager: {decision.get('pct_capital', 0):.0%}[/]" if action == "BUY" else "")
        + (f"\n[dim](Décision automatique: stop/take-profit)[/]" if decision.get("auto") else f"\n[dim]Tokens: {decision.get('input_tokens', '?')} in / {decision.get('output_tokens', '?')} out[/]"),
        title=f"Décision SAL — {snap['date']}",
        border_style=action_color,
    ))

    # Signaux sous la décision
    score = decision["score"]
    bias_color = "green" if "HAUSSIER" in score["biais"] else ("red" if "BAISSIER" in score["biais"] else "yellow")
    console.print(f"Score technique: {score['net_score']:+.2f}/10 — [{bias_color}]{score['biais']}[/]")


def cmd_backtest(args):
    from src.backtest import run_backtest
    from config.settings import INITIAL_CAPITAL

    console.print(f"[bold cyan]Backtest rule-based en cours...[/]")
    if args.start:
        console.print(f"[dim]Période: {args.start} → {args.end or 'aujourd\\'hui'}[/]")

    results = run_backtest(
        start_date=args.start,
        end_date=args.end,
        initial_capital=INITIAL_CAPITAL,
        verbose=args.verbose,
    )

    strat_color = "green" if results["rendement_strategie"] >= 0 else "red"
    bh_color = "green" if results["rendement_buy_hold"] >= 0 else "red"
    alpha_color = "green" if results["alpha"] >= 0 else "red"
    dd_color = "red" if results["max_drawdown_pct"] < -15 else ("yellow" if results["max_drawdown_pct"] < -8 else "green")

    t = Table(title=f"Résultats — {results['periode']}", box=box.ROUNDED)
    t.add_column("Métrique", style="cyan")
    t.add_column("Valeur", justify="right")
    t.add_row("Capital initial", f"{results['capital_initial']:,.0f}$")
    t.add_row("Capital final", f"[bold]{results['capital_final']:,.2f}$[/]")
    t.add_row("Rendement stratégie", f"[{strat_color}]{results['rendement_strategie']:+.2f}%[/]")
    t.add_row("Rendement Buy & Hold", f"[{bh_color}]{results['rendement_buy_hold']:+.2f}%[/]")
    t.add_row("Alpha vs B&H", f"[{alpha_color}]{results['alpha']:+.2f}%[/]")
    t.add_row("Sharpe ratio", f"{results['sharpe_ratio']:.3f}")
    t.add_row("Max drawdown", f"[{dd_color}]{results['max_drawdown_pct']:.2f}%[/]")
    t.add_row("Nombre de trades", str(results["nb_trades"]))
    t.add_row("Taux de réussite", f"{results['win_rate_pct']:.1f}%")
    console.print(t)

    if args.trades and results["trade_log"]:
        console.print()
        tl = Table(title="Historique des trades", box=box.SIMPLE)
        tl.add_column("Date", style="dim")
        tl.add_column("Action", justify="center")
        tl.add_column("Prix", justify="right")
        tl.add_column("Raison")
        for tr in results["trade_log"]:
            color = "green" if tr["action"] == "BUY" else "red"
            tl.add_row(tr["date"], f"[{color}]{tr['action']}[/]", f"{tr['price']:.2f}$", tr["raison"])
        console.print(tl)


def main():
    parser = argparse.ArgumentParser(description="SAL — Agent de trading S&P 500")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("snapshot", help="Affiche les données de marché et indicateurs")

    trade_p = sub.add_parser("trade", help="Lance une décision de trading avec Claude")
    trade_p.add_argument("--model", default="claude-opus-4-7", help="Modèle Claude à utiliser")

    bt_p = sub.add_parser("backtest", help="Backtest rule-based sur données historiques")
    bt_p.add_argument("--start", type=str, default=None, help="Date de début (YYYY-MM-DD)")
    bt_p.add_argument("--end", type=str, default=None, help="Date de fin (YYYY-MM-DD)")
    bt_p.add_argument("--verbose", action="store_true", help="Affiche chaque trade")
    bt_p.add_argument("--trades", action="store_true", help="Affiche le détail des trades")

    args = parser.parse_args()

    if args.command == "snapshot":
        cmd_snapshot(args)
    elif args.command == "trade":
        cmd_trade(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
