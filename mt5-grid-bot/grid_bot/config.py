"""Chargement et validation de la configuration du bot."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints


class ConfigError(ValueError):
    """Configuration invalide."""


@dataclass
class TerminalConfig:
    # Laisser vide pour se connecter au terminal MT5 deja ouvert et deja loggue.
    path: str = ""          # ex: "C:/Program Files/MetaTrader 5/terminal64.exe"
    login: int = 0
    password: str = ""
    server: str = ""
    timeout_ms: int = 30_000
    # Pont Linux : hote/port du serveur RPyC qui expose MetaTrader5 depuis Wine
    # (paquet pymt5linux ou mt5linux). Laisser vide sous Windows.
    bridge_host: str = ""
    bridge_port: int = 18812


@dataclass
class GridConfig:
    # both  : grille bidirectionnelle (achats sous le prix, ventes au-dessus)
    # long  : achats uniquement / short : ventes uniquement
    # trend : direction imposee par le filtre EMA (voir TrendConfig)
    mode: str = "both"
    levels: int = 8                 # nombre de paliers de chaque cote
    # Le pas est exprime en unites de prix (USD pour BTCUSD), pas en "points" broker.
    step_mode: str = "atr"          # "atr" (adaptatif) ou "fixed"
    step_fixed: float = 250.0       # utilise si step_mode == "fixed"
    atr_timeframe: str = "M15"
    atr_period: int = 14
    atr_mult: float = 0.5           # pas = ATR * atr_mult
    step_min: float = 80.0          # borne basse du pas (USD)
    step_max: float = 1500.0        # borne haute du pas (USD)
    tp_mult: float = 1.0            # TP de chaque position = pas * tp_mult
    sl_mult: float = 0.0            # 0 = pas de SL individuel (filet global uniquement)
    rearm_cooldown_sec: int = 30    # delai avant de re-armer un palier apres un TP
    # Stop temporel : age maximal d'une position, en secondes (0 = desactive).
    # C'est le garde-fou central d'une grille : le risque de ruine croit avec le
    # temps passe expose, pas avec le nombre de trades. Borner l'age des
    # positions borne l'accumulation en tendance.
    max_position_age_sec: int = 0
    reanchor_mult: float = 1.5      # re-centrage si |prix - ancre| > pas*levels*ce_facteur
    trail_grid: bool = False        # etendre la grille dans le sens du mouvement


@dataclass
class TrendConfig:
    enabled: bool = False           # active automatiquement si grid.mode == "trend"
    timeframe: str = "H1"
    ema_fast: int = 50
    ema_slow: int = 200


@dataclass
class SizingConfig:
    mode: str = "fixed"             # "fixed" ou "risk"
    lot: float = 0.01
    risk_per_level_pct: float = 0.25  # % de l'equity risquee par palier (mode "risk", exige sl_mult>0)
    lot_min: float = 0.0            # 0 = borne du broker
    lot_max: float = 0.10
    # Facteur multiplicatif par palier (1.0 = pas de martingale). >1 = DANGEREUX.
    martingale_factor: float = 1.0


@dataclass
class RiskConfig:
    max_positions: int = 12         # nombre max de positions ouvertes par le bot
    max_net_lots: float = 0.5       # exposition nette maximale (|lots achat - lots vente|)
    max_total_lots: float = 1.0     # exposition brute maximale
    max_spread: float = 60.0        # spread max autorise, en unites de prix (USD)
    max_drawdown_pct: float = 20.0  # drawdown max depuis le pic d'equity -> arret
    daily_loss_pct: float = 5.0     # perte max sur la journee UTC -> arret
    min_free_margin_pct: float = 40.0  # marge libre minimale (% de l'equity)
    basket_tp_currency: float = 0.0  # 0 = desactive. Cloture globale si PnL flottant >= X
    basket_sl_currency: float = 0.0  # 0 = desactive. Cloture globale si PnL flottant <= -X
    close_all_on_halt: bool = True  # tout fermer quand une limite est franchie
    resume_next_day: bool = True    # reprendre automatiquement le lendemain (UTC)


@dataclass
class SessionConfig:
    enabled: bool = False
    # Fenetres horaires UTC autorisees, format "HH:MM-HH:MM" (peuvent traverser minuit).
    windows: list[str] = field(default_factory=lambda: ["00:00-23:59"])
    trade_weekend: bool = True      # le BTC cote souvent 24/7 chez les brokers CFD
    flat_before_weekend: bool = False


@dataclass
class Config:
    symbol: str = "BTCUSD"
    magic: int = 990101
    tag: str = "GS"                 # prefixe de commentaire des ordres (<= 4 caracteres)
    loop_interval_sec: float = 2.0
    dry_run: bool = True            # True = aucune commande envoyee au broker
    # Refuse de demarrer si le compte connecte n'est pas un compte de demo.
    # A laisser a true tant que la strategie n'a pas fait ses preuves chez toi.
    require_demo_account: bool = False
    log_level: str = "INFO"
    log_file: str = "logs/grid_bot.log"
    state_file: str = "state/grid_state.json"
    deviation_points: int = 50      # slippage tolere sur les ordres au marche
    terminal: TerminalConfig = field(default_factory=TerminalConfig)
    grid: GridConfig = field(default_factory=GridConfig)
    trend: TrendConfig = field(default_factory=TrendConfig)
    sizing: SizingConfig = field(default_factory=SizingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    session: SessionConfig = field(default_factory=SessionConfig)

    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"fichier de configuration introuvable: {path}")
        with path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        cfg = _from_dict(cls, raw, "config")
        cfg.validate()
        return cfg

    def validate(self) -> None:
        g, s, r = self.grid, self.sizing, self.risk
        if not self.symbol:
            raise ConfigError("symbol est obligatoire")
        if len(self.tag) > 4:
            raise ConfigError("tag doit faire 4 caracteres au maximum")
        if g.mode not in ("both", "long", "short", "trend"):
            raise ConfigError(f"grid.mode invalide: {g.mode}")
        if g.step_mode not in ("atr", "fixed"):
            raise ConfigError(f"grid.step_mode invalide: {g.step_mode}")
        if g.levels < 1:
            raise ConfigError("grid.levels doit etre >= 1")
        if g.step_min <= 0 or g.step_max < g.step_min:
            raise ConfigError("grid.step_min/step_max incoherents")
        if g.step_mode == "fixed" and g.step_fixed <= 0:
            raise ConfigError("grid.step_fixed doit etre > 0")
        if g.tp_mult <= 0:
            raise ConfigError("grid.tp_mult doit etre > 0")
        if g.max_position_age_sec < 0:
            raise ConfigError("grid.max_position_age_sec doit etre >= 0")
        if g.sl_mult and g.sl_mult <= g.tp_mult:
            raise ConfigError("grid.sl_mult doit etre > grid.tp_mult (sinon le SL saute avant le TP)")
        if s.mode not in ("fixed", "risk"):
            raise ConfigError(f"sizing.mode invalide: {s.mode}")
        if s.mode == "risk" and g.sl_mult <= 0:
            raise ConfigError("sizing.mode='risk' exige grid.sl_mult > 0")
        if s.mode == "fixed" and s.lot <= 0:
            raise ConfigError("sizing.lot doit etre > 0")
        if s.lot_max <= 0:
            raise ConfigError("sizing.lot_max doit etre > 0")
        if s.martingale_factor < 1.0:
            raise ConfigError("sizing.martingale_factor doit etre >= 1.0")
        if r.max_positions < 1:
            raise ConfigError("risk.max_positions doit etre >= 1")
        if not 0 < r.max_drawdown_pct <= 100:
            raise ConfigError("risk.max_drawdown_pct doit etre dans ]0, 100]")
        if self.loop_interval_sec <= 0:
            raise ConfigError("loop_interval_sec doit etre > 0")
        if self.grid.mode == "trend":
            self.trend.enabled = True

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)


def _from_dict(cls: type, raw: Any, where: str) -> Any:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: objet JSON attendu, recu {type(raw).__name__}")
    known = get_type_hints(cls)
    unknown = set(raw) - set(known)
    if unknown:
        raise ConfigError(f"{where}: cle(s) inconnue(s): {', '.join(sorted(unknown))}")
    kwargs: dict[str, Any] = {}
    for name, value in raw.items():
        ftype = known[name]
        if is_dataclass(ftype):
            kwargs[name] = _from_dict(ftype, value, f"{where}.{name}")
        else:
            kwargs[name] = value
    return cls(**kwargs)


def _to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        return {f.name: _to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, list):
        return [_to_dict(v) for v in obj]
    return obj
