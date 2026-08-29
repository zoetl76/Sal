"""Assemblage et boucle principale du bot."""

from __future__ import annotations

import signal
import time
from types import FrameType

from .broker import Broker, BrokerError
from .config import Config
from .grid import GridEngine
from .logger import setup_logger
from .mt5_broker import MT5Broker
from .paper_broker import PaperBroker

MAX_CONSECUTIVE_ERRORS = 10


class GridBot:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.log = setup_logger("grid_bot", cfg.log_level, cfg.log_file)
        self.running = False
        self.mt5: MT5Broker | None = None
        self.broker: Broker | None = None
        self.engine: GridEngine | None = None

    # ------------------------------------------------------------------ #

    def setup(self, force_live: bool = False) -> None:
        cfg = self.cfg
        self.mt5 = MT5Broker(cfg, self.log)
        self.mt5.connect()

        if cfg.dry_run and not force_live:
            balance = self.mt5.account().balance
            self.broker = PaperBroker(self.mt5, self.log, balance=balance, magic=cfg.magic)
            self.log.warning(
                "MODE PAPIER : cotations reelles, aucun ordre envoye au broker. "
                "Passe dry_run a false pour trader en reel."
            )
        else:
            self.broker = self.mt5
            if cfg.dry_run:
                self.log.info("Lecture directe du compte reel (commande hors boucle).")
            else:
                self.log.warning("MODE REEL : les ordres partent chez le broker.")

        spec = self.broker.symbol_spec()
        self.log.info(
            "Symbole %s | digits=%d point=%g lot=[%.3f..%.2f pas %.3f] stops_level=%.2f",
            spec.name, spec.digits, spec.point, spec.volume_min, spec.volume_max,
            spec.volume_step, spec.stops_level,
        )
        self.engine = GridEngine(cfg, self.broker, self.log)

    def teardown(self) -> None:
        if self.engine:
            self.engine.save_state()
        if self.mt5:
            self.mt5.shutdown()
        self.log.info("Bot arrete.")

    # ------------------------------------------------------------------ #

    def _install_signals(self) -> None:
        def handler(signum: int, _frame: FrameType | None) -> None:
            self.log.info("Signal %s recu, arret propre en cours...", signum)
            self.running = False

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):   # pragma: no cover - hors thread principal
                pass

    def run(self, once: bool = False) -> int:
        self.setup()
        assert self.engine is not None
        self._install_signals()
        self.running = True
        errors = 0

        try:
            while self.running:
                started = time.monotonic()
                try:
                    self.engine.cycle()
                    errors = 0
                except BrokerError as exc:
                    self.log.error("erreur courtier : %s", exc)
                    errors += 1
                except Exception as exc:  # noqa: BLE001 - la boucle ne doit jamais mourir
                    self.log.exception("erreur inattendue : %s", exc)
                    errors += 1

                if errors >= MAX_CONSECUTIVE_ERRORS:
                    self.log.critical("%d erreurs consecutives, arret.", errors)
                    return 1
                if once:
                    break

                elapsed = time.monotonic() - started
                delay = max(0.1, self.cfg.loop_interval_sec - elapsed)
                # Sommeil fractionne pour rester reactif au Ctrl-C.
                while delay > 0 and self.running:
                    chunk = min(0.25, delay)
                    time.sleep(chunk)
                    delay -= chunk
            return 0
        finally:
            self.teardown()

    def flatten(self) -> int:
        """Annule tous les ordres et ferme toutes les positions du bot, puis sort.

        Agit toujours sur le compte reel : c'est le bouton d'arret d'urgence.
        """
        if self.cfg.dry_run:
            self.log.warning("dry_run est actif : la cloture forcee ne fera que journaliser.")
        self.setup(force_live=True)
        assert self.engine is not None and self.broker is not None
        positions = self.broker.positions()
        orders = self.broker.orders()
        self.log.warning("Cloture forcee : %d position(s), %d ordre(s)",
                         len(positions), len(orders))
        self.engine.flatten(positions, orders)
        self.engine.anchor = None
        self.teardown()
        return 0

    def reset(self) -> int:
        """Leve un arret de risque et repart du niveau d'equity courant."""
        self.setup(force_live=True)
        assert self.engine is not None and self.broker is not None
        state = self.engine.risk.state
        if not state.halted:
            self.log.info("Aucun arret en cours, rien a reinitialiser.")
        else:
            equity = self.broker.account().equity
            self.log.warning("Reprise apres arret '%s' (%s) | nouveau pic equity %.2f",
                             state.halt_kind, state.halt_reason, equity)
            self.engine.risk.reset(equity)
        self.engine.anchor = None
        self.engine.save_state()
        self.teardown()
        return 0

    def status(self) -> int:
        self.setup(force_live=True)
        assert self.engine is not None and self.broker is not None
        tick = self.broker.tick()
        account = self.broker.account()
        positions = self.broker.positions()
        orders = self.broker.orders()
        self.engine._refresh_indicators(self.broker.now())
        print(f"Symbole        : {self.cfg.symbol}")
        if tick:
            print(f"Bid/Ask        : {tick.bid:.2f} / {tick.ask:.2f} (spread {tick.spread:.2f})")
        print(f"Equity / solde : {account.equity:.2f} / {account.balance:.2f} {account.currency}")
        print(f"Ancre / pas    : {self.engine.anchor} / {self.engine.step:.2f}")
        print(f"Positions      : {len(positions)} | flottant {sum(p.profit for p in positions):+.2f}")
        for p in sorted(positions, key=lambda x: x.comment):
            print(f"  #{p.ticket} {p.comment} {p.side} {p.volume:.3f} @ {p.price_open:.2f} "
                  f"TP {p.tp:.2f} -> {p.profit:+.2f}")
        print(f"Ordres         : {len(orders)}")
        for o in sorted(orders, key=lambda x: x.comment):
            print(f"  #{o.ticket} {o.comment} {o.side}-limit {o.volume:.3f} @ {o.price:.2f}")
        risk = self.engine.risk.state
        print(f"Risque         : pic equity {risk.peak_equity:.2f} | "
              f"{'ARRETE - ' + risk.halt_reason if risk.halted else 'actif'}")
        self.teardown()
        return 0
