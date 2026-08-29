"""Adaptateur MetaTrader 5 (paquet officiel `MetaTrader5`, Windows uniquement)."""

from __future__ import annotations

import importlib
import logging
from datetime import datetime, timezone

from .broker import (
    Account,
    Bar,
    Broker,
    BrokerError,
    PendingOrder,
    Position,
    SymbolSpec,
    Tick,
)
from .config import Config

TIMEFRAMES = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1", "W1": "TIMEFRAME_W1",
}


BRIDGE_MODULES = ("pymt5linux", "mt5linux")


def import_mt5(cfg: Config | None = None):
    """Retourne l'API MetaTrader5, native ou via le pont Linux.

    Deux chemins, tous deux pleinement supportes :

    * **Windows** — le paquet officiel `MetaTrader5` (seuls des wheels
      `win_amd64` sont publies) parle au terminal local. Rien a configurer.
    * **Linux** — le terminal MT5 tourne sous Wine, avec un Python Windows qui
      expose l'API via un serveur RPyC ; cote Linux, `pymt5linux` ou `mt5linux`
      s'y connecte et fournit un objet dont les methodes et les constantes sont
      identiques a celles du paquet natif. Il suffit de renseigner
      `terminal.bridge_host` dans la configuration.
    """
    try:
        import MetaTrader5 as mt5  # noqa: N813
        return mt5
    except ImportError:
        pass

    host = cfg.terminal.bridge_host if cfg else ""
    if not host:
        raise BrokerError(
            "Le paquet MetaTrader5 n'a pas pu etre importe : seuls des wheels "
            "Windows sont publies sur PyPI.\n"
            "  - Sous Windows : pip install MetaTrader5\n"
            "  - Sous Linux   : MT5 tourne sous Wine et expose son API via un "
            "serveur RPyC. Installe `pip install pymt5linux` (ou `mt5linux`), "
            "lance le serveur cote Wine, puis renseigne terminal.bridge_host "
            "dans ta configuration (voir la section Linux du README)."
        )

    errors = []
    for name in BRIDGE_MODULES:
        try:
            module = importlib.import_module(name)
        except ImportError as exc:
            errors.append(f"{name}: {exc}")
            continue
        port = cfg.terminal.bridge_port
        try:
            return module.MetaTrader5(host=host, port=port)
        except Exception as exc:  # noqa: BLE001 - reseau, Wine, serveur eteint...
            raise BrokerError(
                f"Connexion au pont {name} sur {host}:{port} impossible : {exc}. "
                "Verifie que le terminal MT5 tourne sous Wine et que le serveur "
                "RPyC est demarre de son cote."
            ) from exc

    raise BrokerError(
        f"terminal.bridge_host vaut '{host}' mais aucun pont n'est installe. "
        f"Fais `pip install pymt5linux` (ou `mt5linux`). Details : {'; '.join(errors)}"
    )


class MT5Broker(Broker):
    def __init__(self, cfg: Config, logger: logging.Logger) -> None:
        self.cfg = cfg
        self.log = logger
        self.mt5 = import_mt5(cfg)
        self.symbol = cfg.symbol
        self._spec: SymbolSpec | None = None
        self._filling_pending: int | None = None
        self._filling_market: int | None = None

    # ------------------------------------------------------------------ #
    # Connexion
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        t = self.cfg.terminal
        kwargs: dict = {"timeout": t.timeout_ms}
        if t.path:
            kwargs["path"] = t.path
        if t.login:
            kwargs.update(login=int(t.login), password=t.password, server=t.server)

        if not self.mt5.initialize(**kwargs):
            raise BrokerError(f"initialize() a echoue: {self.mt5.last_error()}")

        info = self.mt5.symbol_info(self.symbol)
        if info is None:
            raise BrokerError(
                f"symbole '{self.symbol}' inconnu du broker. "
                "Verifie son libelle exact dans l'Observation du marche (BTCUSD, BTCUSD.a, ...)."
            )
        if not info.visible and not self.mt5.symbol_select(self.symbol, True):
            raise BrokerError(f"impossible d'activer le symbole '{self.symbol}'")

        acc = self.mt5.account_info()
        if acc is None:
            raise BrokerError(f"account_info() a echoue: {self.mt5.last_error()}")
        if self.cfg.require_demo_account:
            # ACCOUNT_TRADE_MODE_REAL = 2 ; demo = 0, concours = 1.
            if acc.trade_mode == self.mt5.ACCOUNT_TRADE_MODE_REAL:
                raise BrokerError(
                    f"require_demo_account est actif et le compte {acc.login} "
                    f"({acc.server}) est un compte REEL. Connecte le terminal a un "
                    "compte de demonstration, ou passe require_demo_account a false "
                    "en connaissance de cause."
                )
            self.log.info("Compte de demonstration confirme (%s).", acc.server)

        if not acc.trade_allowed and not self.cfg.dry_run:
            raise BrokerError(
                "le trading algorithmique est desactive cote terminal ou cote compte "
                "(Outils > Options > Expert Advisors > Autoriser le trading algorithmique)."
            )

        self._resolve_filling_modes()
        self.log.info(
            "Connecte a MT5 | compte=%s serveur=%s devise=%s levier=1:%s solde=%.2f",
            acc.login, acc.server, acc.currency, acc.leverage, acc.balance,
        )

    def shutdown(self) -> None:
        try:
            self.mt5.shutdown()
        except Exception:  # pragma: no cover - defensif
            pass

    def _resolve_filling_modes(self) -> None:
        mt5 = self.mt5
        info = mt5.symbol_info(self.symbol)
        mask = getattr(info, "filling_mode", 0)
        # Les ordres en attente acceptent RETURN chez la quasi-totalite des brokers.
        self._filling_pending = mt5.ORDER_FILLING_RETURN
        if mask & 2:      # SYMBOL_FILLING_IOC
            self._filling_market = mt5.ORDER_FILLING_IOC
        elif mask & 1:    # SYMBOL_FILLING_FOK
            self._filling_market = mt5.ORDER_FILLING_FOK
        else:
            self._filling_market = mt5.ORDER_FILLING_RETURN

    # ------------------------------------------------------------------ #
    # Lecture
    # ------------------------------------------------------------------ #

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def symbol_spec(self) -> SymbolSpec:
        info = self.mt5.symbol_info(self.symbol)
        if info is None:
            raise BrokerError(f"symbol_info('{self.symbol}') a renvoye None")
        point = info.point or 10 ** -info.digits
        spec = SymbolSpec(
            name=info.name,
            digits=info.digits,
            point=point,
            tick_size=info.trade_tick_size or point,
            tick_value=info.trade_tick_value or 0.0,
            contract_size=info.trade_contract_size or 1.0,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            volume_step=info.volume_step,
            stops_level=max(info.trade_stops_level, info.trade_freeze_level) * point,
        )
        self._spec = spec
        return spec

    def tick(self) -> Tick | None:
        t = self.mt5.symbol_info_tick(self.symbol)
        if t is None or not t.bid or not t.ask:
            return None
        return Tick(
            time=datetime.fromtimestamp(t.time, tz=timezone.utc),
            bid=t.bid,
            ask=t.ask,
        )

    def account(self) -> Account:
        a = self.mt5.account_info()
        if a is None:
            raise BrokerError(f"account_info() a renvoye None: {self.mt5.last_error()}")
        return Account(
            balance=a.balance, equity=a.equity, margin=a.margin,
            margin_free=a.margin_free, currency=a.currency,
        )

    def rates(self, timeframe: str, count: int) -> list[Bar]:
        tf_name = TIMEFRAMES.get(timeframe.upper())
        if tf_name is None:
            raise BrokerError(f"unite de temps non supportee: {timeframe}")
        tf = getattr(self.mt5, tf_name)
        raw = self.mt5.copy_rates_from_pos(self.symbol, tf, 0, count)
        if raw is None:
            return []
        return [
            Bar(
                time=datetime.fromtimestamp(int(r["time"]), tz=timezone.utc),
                open=float(r["open"]), high=float(r["high"]),
                low=float(r["low"]), close=float(r["close"]),
            )
            for r in raw
        ]

    def positions(self) -> list[Position]:
        raw = self.mt5.positions_get(symbol=self.symbol)
        if raw is None:
            return []
        out = []
        for p in raw:
            if p.magic != self.cfg.magic:
                continue
            out.append(Position(
                ticket=p.ticket,
                side="buy" if p.type == self.mt5.POSITION_TYPE_BUY else "sell",
                volume=p.volume,
                price_open=p.price_open,
                tp=p.tp, sl=p.sl,
                profit=p.profit + getattr(p, "swap", 0.0),
                comment=p.comment, magic=p.magic,
                time=datetime.fromtimestamp(p.time, tz=timezone.utc),
            ))
        return out

    def orders(self) -> list[PendingOrder]:
        raw = self.mt5.orders_get(symbol=self.symbol)
        if raw is None:
            return []
        buy_types = (self.mt5.ORDER_TYPE_BUY_LIMIT, self.mt5.ORDER_TYPE_BUY_STOP)
        out = []
        for o in raw:
            if o.magic != self.cfg.magic:
                continue
            out.append(PendingOrder(
                ticket=o.ticket,
                side="buy" if o.type in buy_types else "sell",
                volume=o.volume_current,
                price=o.price_open,
                tp=o.tp, sl=o.sl, comment=o.comment, magic=o.magic,
            ))
        return out

    # ------------------------------------------------------------------ #
    # Ecriture
    # ------------------------------------------------------------------ #

    def place_pending(self, side: str, volume: float, price: float,
                      tp: float, sl: float, comment: str) -> int | None:
        mt5 = self.mt5
        order_type = mt5.ORDER_TYPE_BUY_LIMIT if side == "buy" else mt5.ORDER_TYPE_SELL_LIMIT
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": self.symbol,
            "volume": float(volume),
            "type": order_type,
            "price": float(price),
            "tp": float(tp) if tp else 0.0,
            "sl": float(sl) if sl else 0.0,
            "magic": int(self.cfg.magic),
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_pending,
        }
        result = self._send(request, f"pose {side}-limit {volume}@{price}")
        return result.order if result else None

    def cancel_order(self, ticket: int) -> bool:
        request = {"action": self.mt5.TRADE_ACTION_REMOVE, "order": int(ticket)}
        return self._send(request, f"annule ordre #{ticket}") is not None

    def set_tp_sl(self, position: Position, tp: float, sl: float) -> bool:
        request = {
            "action": self.mt5.TRADE_ACTION_SLTP,
            "symbol": self.symbol,
            "position": int(position.ticket),
            "tp": float(tp) if tp else 0.0,
            "sl": float(sl) if sl else 0.0,
        }
        return self._send(request, f"TP/SL position #{position.ticket}") is not None

    def close_position(self, position: Position) -> bool:
        mt5 = self.mt5
        tick = self.tick()
        if tick is None:
            return False
        is_buy = position.side == "buy"
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": float(position.volume),
            "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
            "position": int(position.ticket),
            "price": tick.bid if is_buy else tick.ask,
            "deviation": int(self.cfg.deviation_points),
            "magic": int(self.cfg.magic),
            "comment": f"{self.cfg.tag}close"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_market,
        }
        return self._send(request, f"cloture position #{position.ticket}") is not None

    # ------------------------------------------------------------------ #

    def _send(self, request: dict, label: str):
        if self.cfg.dry_run:
            self.log.info("[DRY-RUN] %s | %s", label, request)
            return None
        result = self.mt5.order_send(request)
        if result is None:
            self.log.error("%s : order_send a renvoye None (%s)", label, self.mt5.last_error())
            return None
        ok = result.retcode in (self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_PLACED)
        if not ok:
            self.log.error("%s : rejet retcode=%s (%s)", label, result.retcode, result.comment)
            return None
        self.log.info("%s : OK (ticket=%s)", label, result.order or result.deal)
        return result
