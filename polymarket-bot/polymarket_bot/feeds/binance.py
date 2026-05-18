"""Binance websocket feed client for BTC/ETH price data.

Connects to Binance stream API and normalizes data to the common
Tick format. Used as an external signal source.
"""

import asyncio
import json
import time
from typing import Any, Optional

import structlog

from polymarket_bot.feeds.base import BaseFeed, Tick

logger = structlog.get_logger(__name__)

# Binance WebSocket stream endpoint
BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"


class BinanceFeed(BaseFeed):
    """Binance websocket feed for cryptocurrency price data.

    Subscribes to trade streams for specified symbols (e.g., btcusdt, ethusdt)
    and produces normalized Tick objects.
    """

    def __init__(
        self,
        symbols: Optional[list[str]] = None,
        ws_url: str = BINANCE_WS_URL,
    ) -> None:
        """Initialize Binance feed.

        Args:
            symbols: List of trading pair symbols (e.g., ['btcusdt', 'ethusdt']).
            ws_url: WebSocket base URL.
        """
        super().__init__(source_name="binance")
        self.symbols = symbols or ["btcusdt", "ethusdt"]
        self.ws_url = ws_url
        self._ws: Any = None
        self._sequence: int = 0

    def _build_stream_url(self) -> str:
        """Build the combined stream URL for multiple symbols."""
        streams = "/".join(f"{s}@trade" for s in self.symbols)
        return f"{self.ws_url}/{streams}"

    async def connect(self) -> None:
        """Establish connection to Binance websocket."""
        try:
            import websockets

            url = self._build_stream_url()
            self._ws = await websockets.connect(url)
            self._logger.info("binance_connected", symbols=self.symbols)
        except Exception as e:
            self._logger.error("binance_connection_failed", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Close websocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._logger.info("binance_disconnected")

    def parse_message(self, raw: str) -> Optional[Tick]:
        """Parse a Binance trade stream message into a Tick.

        Args:
            raw: Raw JSON message string.

        Returns:
            Tick object or None if message is not a trade.
        """
        try:
            data = json.loads(raw)

            # Binance trade stream format
            if "e" not in data or data["e"] != "trade":
                return None

            symbol = data.get("s", "").lower()
            price = float(data.get("p", 0))
            volume = float(data.get("q", 0))
            trade_time = float(data.get("T", 0)) / 1000.0  # ms to seconds

            self._sequence += 1

            return Tick(
                source="binance",
                token_id=symbol,
                price=price,
                timestamp=trade_time or time.time(),
                volume=volume,
                bid=0.0,
                ask=0.0,
                sequence_number=self._sequence,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            self._logger.warning("binance_parse_error", error=str(e), raw=raw[:100])
            return None
