"""Tests du chemin Linux : MT5 sous Wine, expose via un pont RPyC.

Le paquet officiel MetaTrader5 ne publie que des wheels win_amd64, mais le
terminal tourne sous Wine et `pymt5linux` / `mt5linux` exposent la meme API.
Ces tests verifient la selection du pont sans avoir besoin de Wine.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grid_bot import mt5_broker                       # noqa: E402
from grid_bot.broker import BrokerError               # noqa: E402
from grid_bot.config import Config                    # noqa: E402


def fake_bridge_module(recorder: dict) -> types.ModuleType:
    module = types.ModuleType("faux_pont")

    class MetaTrader5:
        def __init__(self, host: str, port: int) -> None:
            recorder["host"] = host
            recorder["port"] = port

    module.MetaTrader5 = MetaTrader5
    return module


class TestBridgeSelection(unittest.TestCase):
    def setUp(self):
        # On simule une machine sans paquet MetaTrader5 natif.
        self.no_native = mock.patch.dict(sys.modules, {"MetaTrader5": None})

    def test_native_package_wins_when_available(self):
        native = types.ModuleType("MetaTrader5")
        native.marqueur = "natif"
        with mock.patch.dict(sys.modules, {"MetaTrader5": native}):
            self.assertIs(mt5_broker.import_mt5(Config()), native)

    def test_without_bridge_host_the_error_names_both_paths(self):
        with self.no_native:
            with self.assertRaises(BrokerError) as ctx:
                mt5_broker.import_mt5(Config())
        message = str(ctx.exception)
        self.assertIn("Windows", message)
        self.assertIn("Linux", message)
        self.assertIn("pymt5linux", message)

    def test_bridge_is_used_when_host_is_configured(self):
        cfg = Config()
        cfg.terminal.bridge_host = "127.0.0.1"
        cfg.terminal.bridge_port = 18813
        recorder: dict = {}
        module = fake_bridge_module(recorder)
        with self.no_native, mock.patch.object(mt5_broker.importlib, "import_module",
                                               return_value=module):
            client = mt5_broker.import_mt5(cfg)
        self.assertIsInstance(client, module.MetaTrader5)
        self.assertEqual(recorder, {"host": "127.0.0.1", "port": 18813})

    def test_missing_bridge_package_is_reported(self):
        cfg = Config()
        cfg.terminal.bridge_host = "127.0.0.1"
        with self.no_native, mock.patch.object(mt5_broker.importlib, "import_module",
                                               side_effect=ImportError("absent")):
            with self.assertRaises(BrokerError) as ctx:
                mt5_broker.import_mt5(cfg)
        self.assertIn("pip install pymt5linux", str(ctx.exception))

    def test_unreachable_bridge_is_reported_with_host_and_port(self):
        cfg = Config()
        cfg.terminal.bridge_host = "10.0.0.9"
        cfg.terminal.bridge_port = 18812
        module = types.ModuleType("faux_pont")

        class Refuse:
            def __init__(self, host, port):
                raise ConnectionRefusedError("connexion refusee")

        module.MetaTrader5 = Refuse
        with self.no_native, mock.patch.object(mt5_broker.importlib, "import_module",
                                               return_value=module):
            with self.assertRaises(BrokerError) as ctx:
                mt5_broker.import_mt5(cfg)
        message = str(ctx.exception)
        self.assertIn("10.0.0.9:18812", message)
        self.assertIn("Wine", message)

    def test_bridge_defaults_are_inert(self):
        cfg = Config()
        self.assertEqual(cfg.terminal.bridge_host, "")
        self.assertEqual(cfg.terminal.bridge_port, 18812)


if __name__ == "__main__":
    unittest.main(verbosity=2)
