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
    Includes automatic reconnection with exponential backoff.
    """

    def __init__(
        self,
        product_ids: Optional[list[str]] = None,
        ws_url: str = COINBASE_WS_URL,
        reconnect_delay_s: float = 1.0,
        max_reconnect_delay_s: float = 60.0,
    ) -> None:
        """Initialize Coinbase feed.

        Args:
            product_ids: List of product IDs (e.g., ['BTC-USD', 'ETH-USD']).
            ws_url: WebSocket URL.
            reconnect_delay_s: Initial reconnection delay in seconds.
            max_reconnect_delay_s: Maximum reconnection delay in seconds.
        """
        super().__init__(source_name="coinbase")
        self.product_ids = product_ids or ["BTC-USD", "ETH-USD"]
        self.ws_url = ws_url
        self._ws: Any = None
        self._sequence: int = 0
        self._reconnect_delay_s = reconnect_delay_s
        self._max_reconnect_delay_s = max_reconnect_delay_s
        self._current_delay: float = reconnect_delay_s
        self._reconnect_count: int = 0

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
            self._current_delay = self._reconnect_delay_s  # Reset on success
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

    async def reconnect(self) -> None:
        """Reconnect with exponential backoff.

        Retries connection with increasing delays up to max_reconnect_delay_s.
        """
        while self._running:
            self._reconnect_count += 1
            self._logger.info(
                "coinbase_reconnecting",
                delay_s=self._current_delay,
                attempt=self._reconnect_count,
            )
            await asyncio.sleep(self._current_delay)
            try:
                await self.connect()
                self._logger.info("coinbase_reconnected", attempt=self._reconnect_count)
                return
            except Exception as e:
                self._logger.warning(
                    "coinbase_reconnect_failed",
                    error=str(e),
                    delay_s=self._current_delay,
                )
                # Exponential backoff
                self._current_delay = min(
                    self._current_delay * 2, self._max_reconnect_delay_s
                )

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
