"""Coinbase websocket feed client.

Connects to Coinbase WebSocket feed for real-time market data.
Used for cross-verification of prices.
"""

import asyncio
import json
import time
from typing import Any, Optional

import structlog

from polymarket_bot.feeds.base import BaseFeed, Tick

logger = structlog.get_logger(__name__)

# Coinbase WebSocket endpoint
COINBASE_WS_URL = "wss://ws-feed.exchange.coinbase.com"


class CoinbaseFeed(BaseFeed):
    """Coinbase websocket feed for cryptocurrency price data.

    Subscribes to the matches channel for specified product IDs
    (e.g., BTC-USD, ETH-USD) and produces normalized Tick objects.
    """

    def __init__(
        self,
        product_ids: Optional[list[str]] = None,
        ws_url: str = COINBASE_WS_URL,
    ) -> None:
        """Initialize Coinbase feed.

        Args:
            product_ids: List of product IDs (e.g., ['BTC-USD', 'ETH-USD']).
            ws_url: WebSocket URL.
        """
        super().__init__(source_name="coinbase")
        self.product_ids = product_ids or ["BTC-USD", "ETH-USD"]
        self.ws_url = ws_url
        self._ws: Any = None
        self._sequence: int = 0

    async def connect(self) -> None:
        """Establish connection to Coinbase websocket and subscribe."""
        try:
            import websockets

            self._ws = await websockets.connect(self.ws_url)

            # Subscribe to matches channel
            subscribe_msg = json.dumps({
                "type": "subscribe",
                "channels": [{"name": "matches", "product_ids": self.product_ids}],
            })
            await self._ws.send(subscribe_msg)
            self._logger.info("coinbase_connected", products=self.product_ids)
        except Exception as e:
            self._logger.error("coinbase_connection_failed", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Close websocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._logger.info("coinbase_disconnected")

    def parse_message(self, raw: str) -> Optional[Tick]:
        """Parse a Coinbase match message into a Tick.

        Args:
            raw: Raw JSON message string.

        Returns:
            Tick object or None if message is not a match.
        """
        try:
            data = json.loads(raw)

            if data.get("type") != "match":
                return None

            product_id = data.get("product_id", "")
            price = float(data.get("price", 0))
            volume = float(data.get("size", 0))
            # Coinbase timestamps are ISO format, but we use time.time() for consistency
            timestamp = time.time()

            self._sequence += 1

            return Tick(
                source="coinbase",
                token_id=product_id.lower(),
                price=price,
                timestamp=timestamp,
                volume=volume,
                bid=0.0,
                ask=0.0,
                sequence_number=self._sequence,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            self._logger.warning("coinbase_parse_error", error=str(e), raw=raw[:100])
            return None
