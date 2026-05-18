"""Tick recorder that subscribes to websocket tick stream and persists data."""

import asyncio
import csv
import io
import time
from typing import AsyncIterator, Optional

import structlog

from polymarket_bot.data.models import Fill, OrderBookSnapshot, Tick
from polymarket_bot.data.storage import StorageBackend

logger = structlog.get_logger(__name__)


class TickRecorder:
    """Records ticks from websocket stream to persistent storage.

    Subscribes to a tick stream (async iterator) and persists every tick
    to the storage backend. Also supports order book depth snapshots
    and fill recording.
    """

    def __init__(
        self,
        storage: Optional[StorageBackend] = None,
        db_path: str = "data/ticks.db",
        batch_size: int = 100,
    ) -> None:
        """Initialize the tick recorder.

        Args:
            storage: Storage backend instance. If None, creates a new one.
            db_path: Path to SQLite database (used if storage is None).
            batch_size: Number of ticks to batch before flush.
        """
        self.storage = storage or StorageBackend(db_path=db_path, batch_size=batch_size)
        self._recording = False
        self._record_task: Optional[asyncio.Task[None]] = None
        self._tick_count = 0
        self._logger = logger.bind(component="tick_recorder")

    async def start_recording(self, tick_stream: AsyncIterator[Tick]) -> None:
        """Start recording ticks from the given stream.

        Args:
            tick_stream: Async iterator yielding Tick objects.
        """
        if self._recording:
            self._logger.warning("already_recording")
            return

        await self.storage.initialize()
        self._recording = True
        self._record_task = asyncio.create_task(self._record_loop(tick_stream))
        self._logger.info("recording_started")

    async def stop_recording(self) -> None:
        """Stop recording and flush remaining data."""
        self._recording = False
        if self._record_task and not self._record_task.done():
            self._record_task.cancel()
            try:
                await self._record_task
            except asyncio.CancelledError:
                pass

        await self.storage.flush_ticks()
        self._logger.info("recording_stopped", total_ticks=self._tick_count)

    async def _record_loop(self, tick_stream: AsyncIterator[Tick]) -> None:
        """Main recording loop consuming ticks from stream."""
        try:
            async for tick in tick_stream:
                if not self._recording:
                    break
                await self.storage.insert_tick(tick)
                self._tick_count += 1
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._logger.error("recording_error", error=str(e))

    async def record_orderbook_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        """Record an order book depth snapshot.

        Args:
            snapshot: OrderBookSnapshot to persist.
        """
        await self.storage.insert_orderbook_snapshot(snapshot)

    async def record_fill(self, fill: Fill) -> None:
        """Record a trade fill.

        Args:
            fill: Fill to persist.
        """
        await self.storage.insert_fill(fill)

    async def get_ticks(
        self,
        token_id: str,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> list[Tick]:
        """Retrieve ticks for a token in a time range.

        Args:
            token_id: Token identifier.
            start: Start timestamp (inclusive).
            end: End timestamp (inclusive).

        Returns:
            List of Tick objects.
        """
        return await self.storage.get_ticks(token_id, start, end)

    async def get_orderbook_history(
        self,
        token_id: str,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> list[OrderBookSnapshot]:
        """Retrieve order book snapshots for a token.

        Args:
            token_id: Token identifier.
            start: Start timestamp.
            end: End timestamp.

        Returns:
            List of OrderBookSnapshot objects.
        """
        return await self.storage.get_orderbook_history(token_id, start, end)

    async def export_csv(
        self,
        token_id: str,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> str:
        """Export ticks as CSV string.

        Args:
            token_id: Token identifier.
            start: Start timestamp.
            end: End timestamp.

        Returns:
            CSV formatted string of tick data.
        """
        ticks = await self.storage.get_ticks(token_id, start, end)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["timestamp", "token_id", "price", "volume", "bid", "ask", "source", "sequence_number"])
        for tick in ticks:
            writer.writerow([
                tick.timestamp, tick.token_id, tick.price, tick.volume,
                tick.bid, tick.ask, tick.source, tick.sequence_number,
            ])
        return output.getvalue()

    @property
    def is_recording(self) -> bool:
        """Whether the recorder is actively recording."""
        return self._recording

    @property
    def tick_count(self) -> int:
        """Total number of ticks recorded."""
        return self._tick_count
