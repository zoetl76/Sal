#!/usr/bin/env python3
"""Diagnostic de bout en bout de la chaine MT5 sur un VPS Linux.

Concu pour etre lance par une session Claude connectee au VPS : chaque
verification renvoie un verdict tranche (OK / ALERTE / ECHEC) et, en cas de
probleme, la commande a lancer ensuite. Il vaut mieux un controle qui dit
exactement ce qui manque qu'un agent qui deduit l'etat du systeme a partir de
messages d'erreur indirects.

    python3 deploy/doctor.py --config config.json
    python3 deploy/doctor.py --config config.json --json    # sortie machine

Code de sortie : 0 si tout est exploitable, 1 si au moins un ECHEC.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OK, WARN, FAIL, SKIP = "OK", "ALERTE", "ECHEC", "IGNORE"
MARKS = {OK: "  ok  ", WARN: "alerte", FAIL: "ECHEC ", SKIP: "ignore"}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    fix: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "", fix: str = "") -> Check:
        check = Check(name, status, detail, fix)
        self.checks.append(check)
        return check

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    def render(self) -> str:
        width = max(len(c.name) for c in self.checks)
        lines = ["", "=" * (width + 50), "  DIAGNOSTIC DE LA CHAINE MT5", "=" * (width + 50)]
        for c in self.checks:
            lines.append(f"  [{MARKS[c.status]}] {c.name:<{width}}  {c.detail}")
            if c.fix and c.status in (FAIL, WARN):
                lines.append(f"           {'':<{width}}  -> {c.fix}")
        lines.append("=" * (width + 50))
        if self.failed:
            lines.append(f"  {len(self.failed)} echec(s) : "
                         + ", ".join(c.name for c in self.failed))
            lines.append("  Le bot ne doit pas etre demarre tant qu'ils ne sont pas regles.")
        else:
            lines.append("  Chaine exploitable.")
        lines.append("")
        return "\n".join(lines)


def processes(exact_name: str) -> list[tuple[int, str]]:
    """PID et ligne de commande des processus dont le nom est exactement `exact_name`.

    Volontairement pas `pgrep -f` : la recherche plein texte matche la ligne de
    commande du shell qui lance le diagnostic. Quand c'est une session Claude
    qui pilote le VPS, elle tape ces noms-la tout le temps, et chaque
    verification se declarerait vraie toute seule. Le nom dans /proc/<pid>/comm
    ne ment pas.
    """
    found: list[tuple[int, str]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() != exact_name:
                continue
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", "replace").strip()
        except OSError:
            continue
        found.append((int(entry.name), cmdline))
    return found


def one_line(text: str, limit: int = 90) -> str:
    line = " ".join(text.split())
    return line[:limit] + ("…" if len(line) > limit else "")


def sh(*args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=20)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


# --------------------------------------------------------------------- #
# Systeme
# --------------------------------------------------------------------- #

def check_system(rep: Report) -> None:
    mem_mb = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                mem_mb = int(line.split()[1]) // 1024
            if line.startswith("SwapTotal"):
                swap_mb = int(line.split()[1]) // 1024
                break
        else:
            swap_mb = 0
    except OSError:
        swap_mb = 0

    total = mem_mb + swap_mb
    if total >= 2600:
        rep.add("memoire", OK, f"{mem_mb} Mo RAM + {swap_mb} Mo swap")
    elif total >= 1800:
        rep.add("memoire", WARN, f"{mem_mb} Mo RAM + {swap_mb} Mo swap — juste",
                "MT5 sous Wine tient dans ~2 Go ; ajoute du swap si le terminal est tue")
    else:
        rep.add("memoire", FAIL, f"{mem_mb} Mo RAM + {swap_mb} Mo swap — insuffisant",
                "fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile")

    wine = shutil.which("wine")
    if wine:
        _, version = sh("wine", "--version")
        rep.add("wine", OK, version.splitlines()[0] if version else wine)
    else:
        rep.add("wine", FAIL, "absent", "apt-get install -y wine wine64 wine32")

    if shutil.which("Xvfb"):
        rep.add("xvfb installe", OK, "")
    else:
        rep.add("xvfb installe", FAIL, "absent", "apt-get install -y xvfb")


def check_processes(rep: Report, display: str) -> None:
    xvfb = processes("Xvfb")
    on_display = [c for _, c in xvfb if display in c.split()]
    if on_display:
        rep.add("affichage virtuel", OK, f"Xvfb actif sur {display}")
    elif xvfb:
        rep.add("affichage virtuel", FAIL,
                f"Xvfb tourne mais pas sur {display} ({one_line(xvfb[0][1], 50)})",
                f"aligne DISPLAY, ou relance Xvfb sur {display}")
    else:
        rep.add("affichage virtuel", FAIL, f"aucun Xvfb sur {display}",
                "systemctl start gridbot-xvfb")

    if processes("terminal64.exe"):
        rep.add("terminal MT5", OK, "terminal64.exe en cours d'execution")
    else:
        rep.add("terminal MT5", FAIL, "terminal64.exe absent",
                "systemctl start gridbot-mt5-terminal puis attendre ~30 s")


# --------------------------------------------------------------------- #
# Pont RPyC — securite d'abord
# --------------------------------------------------------------------- #

def check_bridge_exposure(rep: Report, port: int) -> None:
    code, out = sh("ss", "-tlnp")
    if code != 0:
        rep.add("pont : ecoute", SKIP, "ss indisponible")
        return

    lines = [l for l in out.splitlines() if f":{port} " in l or l.rstrip().endswith(f":{port}")]
    if not lines:
        rep.add("pont : ecoute", FAIL, f"rien n'ecoute sur le port {port}",
                "systemctl start gridbot-mt5-bridge")
        return

    exposed = [l for l in lines if "0.0.0.0" in l or "[::]" in l or "*:" in l]
    if exposed:
        rep.add("pont : exposition", FAIL,
                f"le port {port} ecoute sur TOUTES les interfaces",
                "Un serveur RPyC classic execute du code arbitraire sans "
                "authentification. Repasse --host 127.0.0.1 dans "
                "gridbot-mt5-bridge.service, redemarre, puis: ufw deny " + str(port))
    else:
        rep.add("pont : exposition", OK, f"127.0.0.1:{port} uniquement")


def check_bridge_reachable(rep: Report, host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=5):
            rep.add("pont : connexion", OK, f"{host}:{port} repond")
            return True
    except OSError as exc:
        rep.add("pont : connexion", FAIL, f"{host}:{port} injoignable ({exc})",
                "journalctl -u gridbot-mt5-bridge -n 50")
        return False


# --------------------------------------------------------------------- #
# Compte et symbole
# --------------------------------------------------------------------- #

def check_trading(rep: Report, cfg) -> None:
    from grid_bot.broker import BrokerError
    from grid_bot.mt5_broker import MT5Broker
    import logging

    log = logging.getLogger("doctor")
    log.addHandler(logging.NullHandler())
    log.propagate = False

    try:
        broker = MT5Broker(cfg, log)
    except BrokerError as exc:
        rep.add("API MetaTrader5", FAIL, one_line(str(exc)),
                "pip install pymt5linux (ou mt5linux) et renseigne terminal.bridge_host")
        return

    try:
        broker.connect()
    except BrokerError as exc:
        rep.add("connexion au compte", FAIL, one_line(str(exc)),
                "verifie les identifiants (variables MT5_LOGIN / MT5_PASSWORD) et le serveur")
        return

    try:
        account = broker.account()
        raw = broker.mt5.account_info()
        mode = getattr(raw, "trade_mode", None)
        modes = {0: "DEMONSTRATION", 1: "CONCOURS", 2: "REEL"}
        label = modes.get(mode, f"inconnu ({mode})")

        if mode == 2:
            rep.add("type de compte", FAIL, f"compte {label} ({raw.login} / {raw.server})",
                    "Bascule le terminal sur un compte de demonstration. "
                    "require_demo_account empechera de toute facon le demarrage.")
        else:
            rep.add("type de compte", OK, f"{label} ({raw.login} / {raw.server})")

        rep.add("equity", OK, f"{account.equity:.2f} {account.currency}")

        if getattr(raw, "trade_allowed", True):
            rep.add("trading autorise", OK, "")
        else:
            rep.add("trading autorise", FAIL, "refuse par le terminal ou le compte",
                    "Outils > Options > Expert Advisors > Autoriser le trading algorithmique")

        spec = broker.symbol_spec()
        rep.add("symbole", OK, f"{spec.name} ({spec.digits} decimales, "
                               f"lot {spec.volume_min}-{spec.volume_max})")

        tick = broker.tick()
        if tick is None:
            rep.add("cotation", FAIL, "aucun tick",
                    "le symbole est-il visible dans l'Observation du marche ?")
        else:
            spread = tick.spread
            limit = cfg.risk.max_spread
            if spread > limit:
                rep.add("spread", WARN, f"{spread:.2f} > max_spread {limit:.2f}",
                        "le bot ne posera aucun ordre ; releve max_spread ou attends "
                        "une heure plus liquide")
            else:
                rep.add("spread", OK, f"{spread:.2f} (limite {limit:.2f})")

        positions = broker.positions()
        orders = broker.orders()
        rep.add("positions du bot", OK,
                f"{len(positions)} position(s), {len(orders)} ordre(s) en attente")
    except BrokerError as exc:
        rep.add("interrogation du compte", FAIL, one_line(str(exc)))
    finally:
        broker.shutdown()


# --------------------------------------------------------------------- #

def check_config(rep: Report, cfg) -> None:
    if cfg.require_demo_account:
        rep.add("garde-fou compte", OK, "require_demo_account actif")
    else:
        rep.add("garde-fou compte", WARN, "require_demo_account desactive",
                "tant que la strategie n'a pas fait ses preuves, laisse-le a true")

    if cfg.sizing.martingale_factor > 1.0:
        rep.add("martingale", FAIL, f"facteur {cfg.sizing.martingale_factor}",
                "remets-le a 1.0 : au-dela la grille finit statistiquement a zero")
    else:
        rep.add("martingale", OK, "desactivee")

    dd = cfg.risk.max_drawdown_pct
    rep.add("budget de risque", OK if dd <= 20 else WARN,
            f"arret terminal a -{dd:.0f}% de l'equity",
            "" if dd <= 20 else "au-dela de 20% l'arret ne protege plus grand-chose")

    rep.add("mode", OK if not cfg.dry_run else WARN,
            "ordres reels" if not cfg.dry_run else "mode papier (aucun ordre envoye)",
            "" if not cfg.dry_run else "passe dry_run a false pour trader la demo")


def check_services(rep: Report) -> None:
    if not shutil.which("systemctl"):
        rep.add("services", SKIP, "systemd absent")
        return
    _, probe = sh("systemctl", "is-system-running")
    # "offline" = systemd installe mais pas PID 1 (conteneur). Interroger les
    # unites dans ce cas ne renvoie que du bruit.
    if probe.strip() == "offline" or "has not been booted with systemd" in probe:
        rep.add("services", SKIP, "systemd non utilise comme init (conteneur ?)")
        return
    for unit in ("gridbot-xvfb", "gridbot-mt5-terminal",
                 "gridbot-mt5-bridge", "gridbot-grid-bot"):
        code, out = sh("systemctl", "is-active", unit)
        state = one_line(out) or "inconnu"
        if state == "active":
            rep.add(f"service {unit}", OK, state)
        elif unit == "gridbot-grid-bot":
            rep.add(f"service {unit}", WARN, state,
                    "normal tant que le diagnostic n'est pas vert")
        else:
            rep.add(f"service {unit}", FAIL, state, f"systemctl start {unit}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnostic de la chaine MT5.")
    parser.add_argument("-c", "--config", default="config.json")
    parser.add_argument("--display", default=os.environ.get("DISPLAY", ":99"))
    parser.add_argument("--json", action="store_true", help="sortie machine")
    parser.add_argument("--skip-trading", action="store_true",
                        help="ne pas interroger le broker (verifications systeme seules)")
    args = parser.parse_args(argv)

    rep = Report()
    check_system(rep)
    check_processes(rep, args.display)

    cfg = None
    try:
        from grid_bot.config import Config, ConfigError
        cfg = Config.load(args.config)
        rep.add("configuration", OK, f"{args.config} valide")
    except Exception as exc:  # noqa: BLE001 - fichier absent, JSON casse, cle inconnue
        rep.add("configuration", FAIL, one_line(f"{type(exc).__name__}: {exc}"),
                "corrige config.json avant toute autre chose")

    if cfg is not None:
        check_config(rep, cfg)
        port = cfg.terminal.bridge_port
        check_bridge_exposure(rep, port)
        host = cfg.terminal.bridge_host or "127.0.0.1"
        reachable = check_bridge_reachable(rep, host, port) if cfg.terminal.bridge_host else True
        if not args.skip_trading and reachable:
            check_trading(rep, cfg)

    check_services(rep)

    if args.json:
        print(json.dumps({"checks": [c.__dict__ for c in rep.checks],
                          "failed": len(rep.failed)}, indent=2, ensure_ascii=False))
    else:
        print(rep.render())
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
