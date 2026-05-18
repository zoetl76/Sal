"""Polymarket-specific websocket feed client.

Connects to CLOB websocket for order book data and Gamma websocket
for market resolution data. Parses Polymarket message formats into
normalized Tick dataclass.
"""

import asyncio
import json
import time
from typing import Any, AsyncIterator, Optional

import structlog

from polymarket_bot.feeds.base import BaseFeed, Tick

logger = structlog.get_logger(__name__)

# Polymarket WebSocket endpoints
CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
GAMMA_WS_URL = "wss://gamma-api.polymarket.com/ws"


class PolymarketFeed(BaseFeed):
    """Polymarket CLOB and Gamma websocket feed.

    Connects to both the CLOB websocket for real-time order book
    updates and the Gamma websocket for market resolution data.
    Includes automatic reconnection with exponential backoff.
    """

    def __init__(
        self,
        token_ids: Optional[list[str]] = None,
        clob_url: str = CLOB_WS_URL,
        gamma_url: str = GAMMA_WS_URL,
        reconnect_delay_s: float = 1.0,
        max_reconnect_delay_s: float = 60.0,
    ) -> None:
        """Initialize Polymarket feed.

        Args:
            token_ids: List of token IDs to subscribe to.
            clob_url: WebSocket URL for CLOB data.
            gamma_url: WebSocket URL for Gamma data.
            reconnect_delay_s: Initial reconnection delay in seconds.
            max_reconnect_delay_s: Maximum reconnection delay in seconds.
        """
        super().__init__(source_name="polymarket")
        self.token_ids = token_ids or []
        self.clob_url = clob_url
        self.gamma_url = gamma_url
        self._clob_ws: Any = None
        self._gamma_ws: Any = None
        self._sequence: int = 0
        self._reconnect_delay_s = reconnect_delay_s
        self._max_reconnect_delay_s = max_reconnect_delay_s
        self._current_delay: float = reconnect_delay_s
        self._reconnect_count: int = 0

    async def connect(self) -> None:
        """Establish connections to CLOB and Gamma websockets."""
        try:
            import websockets

            self._clob_ws = await websockets.connect(self.clob_url)
            self._gamma_ws = await websockets.connect(self.gamma_url)

            # Subscribe to token channels
            for token_id in self.token_ids:
                subscribe_msg = json.dumps({
                    "type": "subscribe",
                    "channel": "market",
                    "assets_id": token_id,
                })
                await self._clob_ws.send(subscribe_msg)

            self._current_delay = self._reconnect_delay_s  # Reset on success
            self._logger.info("polymarket_connected", token_count=len(self.token_ids))
        except Exception as e:
            self._logger.error("polymarket_connection_failed", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Close websocket connections."""
        if self._clob_ws:
            await self._clob_ws.close()
            self._clob_ws = None
        if self._gamma_ws:
            await self._gamma_ws.close()
            self._gamma_ws = None
        self._logger.info("polymarket_disconnected")

    async def reconnect(self) -> None:
        """Reconnect with exponential backoff.

        Retries connection with increasing delays up to max_reconnect_delay_s.
        """
        while self._running:
            self._reconnect_count += 1
            self._logger.info(
                "polymarket_reconnecting",
                delay_s=self._current_delay,
                attempt=self._reconnect_count,
            )
            await asyncio.sleep(self._current_delay)
            try:
                await self.connect()
                self._logger.info("polymarket_reconnected", attempt=self._reconnect_count)
                return
            except Exception as e:
                self._logger.warning(
                    "polymarket_reconnect_failed",
                    error=str(e),
                    delay_s=self._current_delay,
                )
                # Exponential backoff
                self._current_delay = min(
                    self._current_delay * 2, self._max_reconnect_delay_s
                )

    async def _listen(self) -> AsyncIterator[Tick]:
        """Listen for messages from the Polymarket CLOB websocket.

        Yields:
            Parsed Tick objects from the CLOB websocket stream.

        Raises:
            Exception: On websocket connection loss.
        """
        while self._running and self._clob_ws:
            raw = await self._clob_ws.recv()
            tick = self._parse_clob_message(raw)
            if tick is not None:
                yield tick

    def _parse_clob_message(self, raw: str) -> Optional[Tick]:
        """Parse a CLOB websocket message into a Tick.

        Args:
            raw: Raw JSON message string.

        Returns:
            Tick object or None if message is not a price update.
        """
        try:
            data = json.loads(raw)
            msg_type = data.get("type", "")

            if msg_type not in ("book", "price_change", "trade"):
                return None

            token_id = data.get("asset_id", data.get("market", ""))
            price = float(data.get("price", data.get("best_bid", 0)))
            bid = float(data.get("best_bid", 0))
            ask = float(data.get("best_ask", 0))
            volume = float(data.get("size", data.get("volume", 0)))

            self._sequence += 1

            return Tick(
                source="polymarket_clob",
                token_id=token_id,
                price=price,
                timestamp=time.time(),
                volume=volume,
                bid=bid,
                ask=ask,
                sequence_number=self._sequence,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            self._logger.warning("clob_parse_error", error=str(e), raw=raw[:100])
            return None

    def _parse_gamma_message(self, raw: str) -> Optional[Tick]:
        """Parse a Gamma websocket message into a Tick.

        Args:
            raw: Raw JSON message string.

        Returns:
            Tick object or None if message is not relevant.
        """
        try:
            data = json.loads(raw)
            msg_type = data.get("type", "")

            if msg_type not in ("market_update", "resolution"):
                return None

            token_id = data.get("condition_id", data.get("market_id", ""))
            price = float(data.get("outcome_price", data.get("price", 0)))

            self._sequence += 1

            return Tick(
                source="polymarket_gamma",
                token_id=token_id,
                price=price,
                timestamp=time.time(),
                volume=0.0,
                bid=0.0,
                ask=0.0,
                sequence_number=self._sequence,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            self._logger.warning("gamma_parse_error", error=str(e), raw=raw[:100])
            return None
