"""SQLite storage backend with async connection pooling."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

import aiosqlite
import structlog

from polymarket_bot.data.models import Fill, OrderBookSnapshot, Tick

logger = structlog.get_logger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    token_id TEXT NOT NULL,
    price REAL NOT NULL,
    volume REAL DEFAULT 0.0,
    bid REAL DEFAULT 0.0,
    ask REAL DEFAULT 0.0,
    source TEXT NOT NULL,
    sequence_number INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ticks_token_time ON ticks(token_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_ticks_timestamp ON ticks(timestamp);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    token_id TEXT NOT NULL,
    depth_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orderbook_token_time ON orderbook_snapshots(token_id, timestamp);

CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    token_id TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    side TEXT NOT NULL,
    slippage REAL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_fills_token_time ON fills(token_id, timestamp);
"""


class StorageBackend:
    """SQLite storage backend with connection pooling and bulk operations."""

    def __init__(
        self,
        db_path: str = "data/ticks.db",
        pool_size: int = 3,
        batch_size: int = 100,
        retention_days: Optional[int] = None,
    ) -> None:
        """Initialize storage backend.

        Args:
            db_path: Path to SQLite database file.
            pool_size: Number of connections in the pool.
            batch_size: Number of records to batch before flushing.
            retention_days: Days of data to retain (None for unlimited).
        """
        self.db_path = db_path
        self.pool_size = pool_size
        self.batch_size = batch_size
        self.retention_days = retention_days
        self._connections: list[aiosqlite.Connection] = []
        self._conn_semaphore = asyncio.Semaphore(pool_size)
        self._tick_buffer: list[Tick] = []
        self._initialized = False
        self._logger = logger.bind(component="storage")

    async def initialize(self) -> None:
        """Initialize the database and connection pool."""
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        conn = await aiosqlite.connect(self.db_path)
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()
        await conn.close()

        self._initialized = True
        self._logger.info("storage_initialized", db_path=self.db_path)

    async def _get_connection(self) -> aiosqlite.Connection:
        """Get a connection from the pool."""
        await self._conn_semaphore.acquire()
        conn = await aiosqlite.connect(self.db_path)
        return conn

    async def _release_connection(self, conn: aiosqlite.Connection) -> None:
        """Release a connection back to the pool."""
        await conn.close()
        self._conn_semaphore.release()

    async def insert_tick(self, tick: Tick) -> None:
        """Insert a single tick into the buffer, flushing if needed."""
        self._tick_buffer.append(tick)
        if len(self._tick_buffer) >= self.batch_size:
            await self.flush_ticks()

    async def insert_ticks(self, ticks: list[Tick]) -> None:
        """Bulk insert ticks directly."""
        if not ticks:
            return

        conn = await self._get_connection()
        try:
            await conn.executemany(
                """INSERT INTO ticks (timestamp, token_id, price, volume, bid, ask, source, sequence_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (t.timestamp, t.token_id, t.price, t.volume, t.bid, t.ask, t.source, t.sequence_number)
                    for t in ticks
                ],
            )
            await conn.commit()
        finally:
            await self._release_connection(conn)

    async def flush_ticks(self) -> None:
        """Flush the tick buffer to database."""
        if not self._tick_buffer:
            return

        ticks = self._tick_buffer[:]
        self._tick_buffer.clear()
        await self.insert_ticks(ticks)

    async def get_ticks(
        self,
        token_id: str,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> list[Tick]:
        """Query ticks by token_id and optional time range.

        Args:
            token_id: Token identifier to query.
            start: Start timestamp (inclusive).
            end: End timestamp (inclusive).

        Returns:
            List of Tick objects matching the query.
        """
        conn = await self._get_connection()
        try:
            query = "SELECT timestamp, token_id, price, volume, bid, ask, source, sequence_number FROM ticks WHERE token_id = ?"
            params: list[Any] = [token_id]

            if start is not None:
                query += " AND timestamp >= ?"
                params.append(start)
            if end is not None:
                query += " AND timestamp <= ?"
                params.append(end)

            query += " ORDER BY timestamp ASC"

            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()

            return [
                Tick(
                    source=row[6],
                    token_id=row[1],
                    price=row[2],
                    timestamp=row[0],
                    volume=row[3],
                    bid=row[4],
                    ask=row[5],
                    sequence_number=row[7],
                )
                for row in rows
            ]
        finally:
            await self._release_connection(conn)

    async def insert_orderbook_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        """Insert an order book snapshot."""
        conn = await self._get_connection()
        try:
            depth_json = json.dumps({"bids": [list(b) for b in snapshot.bids], "asks": [list(a) for a in snapshot.asks]})
            await conn.execute(
                """INSERT INTO orderbook_snapshots (timestamp, token_id, depth_json)
                   VALUES (?, ?, ?)""",
                (snapshot.timestamp, snapshot.token_id, depth_json),
            )
            await conn.commit()
        finally:
            await self._release_connection(conn)

    async def get_orderbook_history(
        self,
        token_id: str,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> list[OrderBookSnapshot]:
        """Query order book snapshots by token_id and time range."""
        conn = await self._get_connection()
        try:
            query = "SELECT timestamp, token_id, depth_json FROM orderbook_snapshots WHERE token_id = ?"
            params: list[Any] = [token_id]

            if start is not None:
                query += " AND timestamp >= ?"
                params.append(start)
            if end is not None:
                query += " AND timestamp <= ?"
                params.append(end)

            query += " ORDER BY timestamp ASC"

            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()

            results = []
            for row in rows:
                depth = json.loads(row[2])
                results.append(
                    OrderBookSnapshot(
                        timestamp=row[0],
                        token_id=row[1],
                        bids=tuple(tuple(b) for b in depth.get("bids", [])),
                        asks=tuple(tuple(a) for a in depth.get("asks", [])),
                    )
                )
            return results
        finally:
            await self._release_connection(conn)

    async def insert_fill(self, fill: Fill) -> None:
        """Insert a fill record."""
        conn = await self._get_connection()
        try:
            await conn.execute(
                """INSERT INTO fills (timestamp, token_id, price, size, side, slippage)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (fill.timestamp, fill.token_id, fill.price, fill.size, fill.side, fill.slippage),
            )
            await conn.commit()
        finally:
            await self._release_connection(conn)

    async def get_fills(
        self,
        token_id: str,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> list[Fill]:
        """Query fills by token_id and time range."""
        conn = await self._get_connection()
        try:
            query = "SELECT timestamp, token_id, price, size, side, slippage FROM fills WHERE token_id = ?"
            params: list[Any] = [token_id]

            if start is not None:
                query += " AND timestamp >= ?"
                params.append(start)
            if end is not None:
                query += " AND timestamp <= ?"
                params.append(end)

            query += " ORDER BY timestamp ASC"

            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()

            return [
                Fill(
                    timestamp=row[0],
                    token_id=row[1],
                    price=row[2],
                    size=row[3],
                    side=row[4],
                    slippage=row[5],
                )
                for row in rows
            ]
        finally:
            await self._release_connection(conn)

    async def get_ohlcv(
        self,
        token_id: str,
        interval_seconds: float = 60.0,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """Aggregate ticks into OHLCV bars.

        Args:
            token_id: Token identifier.
            interval_seconds: Bar interval in seconds.
            start: Start timestamp.
            end: End timestamp.

        Returns:
            List of OHLCV bar dictionaries with keys:
            timestamp, open, high, low, close, volume.
        """
        ticks = await self.get_ticks(token_id, start, end)
        if not ticks:
            return []

        bars: list[dict[str, Any]] = []
        bar_start = ticks[0].timestamp
        bar_ticks: list[Tick] = []

        for tick in ticks:
            if tick.timestamp >= bar_start + interval_seconds:
                if bar_ticks:
                    bars.append(self._make_bar(bar_start, bar_ticks))
                bar_start = bar_start + interval_seconds
                # Skip empty intervals
                while tick.timestamp >= bar_start + interval_seconds:
                    bar_start += interval_seconds
                bar_ticks = [tick]
            else:
                bar_ticks.append(tick)

        if bar_ticks:
            bars.append(self._make_bar(bar_start, bar_ticks))

        return bars

    @staticmethod
    def _make_bar(bar_start: float, ticks: list[Tick]) -> dict[str, Any]:
        """Create an OHLCV bar from a list of ticks."""
        prices = [t.price for t in ticks]
        return {
            "timestamp": bar_start,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": sum(t.volume for t in ticks),
        }

    async def apply_retention_policy(self) -> int:
        """Delete data older than retention_days.

        Returns:
            Number of rows deleted.
        """
        if self.retention_days is None:
            return 0

        cutoff = time.time() - (self.retention_days * 86400)
        conn = await self._get_connection()
        try:
            total_deleted = 0
            for table in ("ticks", "orderbook_snapshots", "fills"):
                cursor = await conn.execute(
                    f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,)
                )
                total_deleted += cursor.rowcount
            await conn.commit()
            self._logger.info("retention_applied", deleted=total_deleted, cutoff_days=self.retention_days)
            return total_deleted
        finally:
            await self._release_connection(conn)

    async def compact(self) -> None:
        """Run VACUUM to compact the database."""
        conn = await self._get_connection()
        try:
            await conn.execute("VACUUM")
            self._logger.info("database_compacted")
        finally:
            await self._release_connection(conn)

    async def close(self) -> None:
        """Close all connections and flush remaining data."""
        await self.flush_ticks()
        self._logger.info("storage_closed")
