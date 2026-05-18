"""External data feeds (Binance, Coinbase, Polymarket).

Provides normalized Tick dataclass and feed implementations for
multiple data sources.
"""

from polymarket_bot.feeds.base import BaseFeed, Tick
from polymarket_bot.feeds.binance import BinanceFeed
from polymarket_bot.feeds.coinbase import CoinbaseFeed
from polymarket_bot.feeds.polymarket import PolymarketFeed

__all__ = [
    "BaseFeed",
    "Tick",
    "BinanceFeed",
    "CoinbaseFeed",
    "PolymarketFeed",
]
