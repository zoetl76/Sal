"""Generateur de marches synthetiques realistes pour le backtest.

Une marche aleatoire gaussienne ne ressemble pas au BTC : elle n'a ni
regroupement de volatilite, ni queues epaisses, ni regimes. Optimiser une
grille dessus donne des parametres qui ne survivent pas au premier vrai
marche directionnel.

Ce module produit des series qui reproduisent les proprietes statistiques
connues du BTC :
  * volatilite auto-regressive facon GARCH(1,1) (les fortes variations
    s'enchainent) ;
  * innovations de Student (df=4) : krachs et bougies extremes ;
  * regimes de marche (range / haussier / baissier / krach) avec
    transitions markoviennes ;
  * OHLC construit a partir d'un chemin intra-bougie, pas d'extremes
    tires au hasard.

Ce n'est pas un substitut a de vraies donnees : c'est un banc d'essai
pour verifier qu'un jeu de parametres survit a tous les regimes.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .broker import Bar

# Volatilite BTC : ~55 % annualise -> ~2,9 % par jour -> ~0,17 % par bougie M5.
BASE_VOL_M5 = 0.0017
BARS_PER_DAY_M5 = 288


@dataclass(frozen=True)
class Regime:
    name: str
    drift_per_day: float      # derive en fraction de prix par jour
    vol_mult: float
    mean_reversion: float     # 0 = marche aleatoire, >0 = rappel vers la moyenne
    mean_duration_days: float


REGIMES: dict[str, Regime] = {
    "range":  Regime("range",  0.000, 0.85, 0.020, 6.0),
    "bull":   Regime("bull",  +0.012, 1.00, 0.000, 8.0),
    "bear":   Regime("bear",  -0.010, 1.15, 0.000, 6.0),
    "crash":  Regime("crash", -0.045, 2.40, 0.000, 1.2),
    "melt":   Regime("melt",  +0.035, 2.00, 0.000, 1.2),   # squeeze haussier
    "chop":   Regime("chop",   0.000, 1.60, 0.005, 4.0),
}

# Scenarios exposes au backtest et a l'optimiseur.
SCENARIOS = ["range", "bull", "bear", "crash", "chop", "mixed"]


def _student_t(rng: random.Random, df: float = 4.0) -> float:
    """Tirage de Student normalise a variance 1 (queues epaisses)."""
    z = rng.gauss(0.0, 1.0)
    chi2 = 2.0 * rng.gammavariate(df / 2.0, 1.0)
    t = z / math.sqrt(chi2 / df)
    return t / math.sqrt(df / (df - 2.0))


class _Garch:
    """Volatilite conditionnelle GARCH(1,1), persistance ~0,98.

    La volatilite est plafonnee a `cap_mult` fois la volatilite de long terme :
    sans ce plafond, l'amplification par le multiplicateur de regime rend le
    processus explosif et produit des series qui n'ont plus rien d'un marche.
    """

    def __init__(self, base_vol: float, alpha: float = 0.08, beta: float = 0.90,
                 cap_mult: float = 6.0) -> None:
        self.alpha = alpha
        self.beta = beta
        self.omega = base_vol ** 2 * (1.0 - alpha - beta)
        self.var = base_vol ** 2
        self.var_cap = (base_vol * cap_mult) ** 2

    def next_sigma(self, last_return: float) -> float:
        self.var = self.omega + self.alpha * last_return ** 2 + self.beta * self.var
        self.var = min(max(self.var, 1e-12), self.var_cap)
        return math.sqrt(self.var)


def _regime_sequence(scenario: str, bars: int, rng: random.Random,
                     bars_per_day: float) -> list[Regime]:
    """Suite de regimes bougie par bougie."""
    if scenario == "crash":
        # Un krach reel est un episode, pas un etat permanent : calme, chute
        # violente, capitulation, puis rebond partiel.
        plan = [("range", 0.30), ("crash", 0.12), ("bear", 0.23),
                ("range", 0.20), ("melt", 0.15)]
        sequence: list[Regime] = []
        for name, share in plan:
            sequence.extend([REGIMES[name]] * int(bars * share))
        sequence.extend([REGIMES["range"]] * (bars - len(sequence)))
        return sequence[:bars]

    if scenario != "mixed":
        return [REGIMES[scenario]] * bars

    # Chaine de Markov : le range domine, les krachs sont rares et courts.
    weights = {"range": 0.42, "chop": 0.20, "bull": 0.18,
               "bear": 0.13, "crash": 0.04, "melt": 0.03}
    names = list(weights)
    probs = [weights[n] for n in names]

    sequence: list[Regime] = []
    current = REGIMES[rng.choices(names, probs)[0]]
    while len(sequence) < bars:
        duration = max(1, int(rng.expovariate(1.0 / (current.mean_duration_days * bars_per_day))))
        sequence.extend([current] * duration)
        current = REGIMES[rng.choices(names, probs)[0]]
    return sequence[:bars]


def generate(scenario: str = "mixed", bars: int = 10_000, seed: int = 1,
             start_price: float = 65_000.0, minutes: int = 5,
             substeps: int = 8, base_vol: float | None = None) -> list[Bar]:
    """Genere `bars` bougies OHLC pour le scenario demande."""
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario inconnu: {scenario} (choix: {', '.join(SCENARIOS)})")

    bars_per_day = 1440.0 / minutes
    vol = (base_vol if base_vol is not None
           else BASE_VOL_M5 * math.sqrt(minutes / 5.0))

    rng = random.Random(seed)
    garch = _Garch(vol)
    regimes = _regime_sequence(scenario, bars, rng, bars_per_day)

    t0 = datetime(2023, 1, 1, tzinfo=timezone.utc)
    price = start_price
    log_anchor = math.log(start_price)
    last_return = 0.0
    out: list[Bar] = []

    for i, regime in enumerate(regimes):
        sigma = garch.next_sigma(last_return) * regime.vol_mult
        drift = regime.drift_per_day / bars_per_day
        # Rappel vers la moyenne mobile lente du log-prix (regimes de range).
        pull = regime.mean_reversion * (log_anchor - math.log(price))

        step_sigma = sigma / math.sqrt(substeps)
        step_mu = (drift + pull) / substeps

        path = [price]
        for _ in range(substeps):
            # Les innovations de Student sont bornees a 8 ecarts-types : au-dela
            # ce n'est plus une queue epaisse, c'est un artefact de simulation.
            shock = max(-8.0, min(8.0, _student_t(rng)))
            path.append(path[-1] * math.exp(step_mu + step_sigma * shock))

        bar_open, bar_close = path[0], path[-1]
        out.append(Bar(
            time=t0 + timedelta(minutes=minutes * i),
            open=round(bar_open, 2),
            high=round(max(path), 2),
            low=round(min(path), 2),
            close=round(bar_close, 2),
        ))

        # Retour desamplifie : sans ca le multiplicateur de regime se reinjecte
        # dans la variance GARCH et le processus devient explosif.
        last_return = (math.log(bar_close / bar_open) / regime.vol_mult
                       if bar_open > 0 else 0.0)
        price = bar_close
        # L'ancre de rappel suit le prix avec une forte inertie (~1 jour).
        log_anchor += (math.log(price) - log_anchor) / bars_per_day

    return out


def describe(bars: list[Bar]) -> dict:
    """Statistiques descriptives d'une serie generee (controle de realisme)."""
    closes = [b.close for b in bars]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / n
    sd = math.sqrt(var)
    kurt = (sum((r - mean) ** 4 for r in rets) / n) / (var ** 2) if var > 0 else 0.0
    minutes = (bars[1].time - bars[0].time).total_seconds() / 60.0
    per_year = 525_600 / minutes
    return {
        "bougies": len(bars),
        "prix_debut": closes[0],
        "prix_fin": closes[-1],
        "variation_pct": (closes[-1] / closes[0] - 1.0) * 100.0,
        "vol_annualisee_pct": sd * math.sqrt(per_year) * 100.0,
        "kurtosis": kurt,
        "amplitude_max_pct": (max(closes) / min(closes) - 1.0) * 100.0,
    }
