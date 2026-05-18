"""Tests for data recording and storage."""

import asyncio
import os
import tempfile
import time

import pytest
import pytest_asyncio

from polymarket_bot.data.models import Fill, OrderBookSnapshot, Tick
from polymarket_bot.data.recorder import TickRecorder
from polymarket_bot.data.storage import StorageBackend


@pytest_asyncio.fixture
async def storage(tmp_path):
    """Create a temporary storage backend."""
    db_path = str(tmp_path / "test_ticks.db")
    backend = StorageBackend(db_path=db_path, batch_size=10)
    await backend.initialize()
    yield backend
    await backend.close()


@pytest_asyncio.fixture
async def recorder(tmp_path):
    """Create a temporary tick recorder."""
    db_path = str(tmp_path / "test_recorder.db")
    backend = StorageBackend(db_path=db_path, batch_size=5)
    rec = TickRecorder(storage=backend)
    yield rec


class TestTickPersistence:
    """Tests for tick persistence."""

    @pytest.mark.asyncio
    async def test_insert_and_retrieve_tick(self, storage):
        """Verify a single tick can be inserted and retrieved."""
        tick = Tick(
            source="polymarket",
            token_id="token_abc",
            price=0.55,
            timestamp=1000.0,
            volume=100.0,
            bid=0.54,
            ask=0.56,
            sequence_number=1,
        )
        await storage.insert_tick(tick)
        await storage.flush_ticks()

        ticks = await storage.get_ticks("token_abc")
        assert len(ticks) == 1
        assert ticks[0].price == 0.55
        assert ticks[0].token_id == "token_abc"
        assert ticks[0].source == "polymarket"
        assert ticks[0].volume == 100.0
        assert ticks[0].bid == 0.54
        assert ticks[0].ask == 0.56

    @pytest.mark.asyncio
    async def test_bulk_insert(self, storage):
        """Verify bulk insert of multiple ticks."""
        ticks = [
            Tick(
                source="polymarket",
                token_id="token_abc",
                price=0.50 + i * 0.01,
                timestamp=1000.0 + i,
                volume=10.0,
                bid=0.49 + i * 0.01,
                ask=0.51 + i * 0.01,
                sequence_number=i,
            )
            for i in range(50)
        ]
        await storage.insert_ticks(ticks)

        result = await storage.get_ticks("token_abc")
        assert len(result) == 50

    @pytest.mark.asyncio
    async def test_query_by_time_range(self, storage):
        """Verify time-range queries work correctly."""
        ticks = [
            Tick(
                source="polymarket",
                token_id="token_abc",
                price=0.50 + i * 0.01,
                timestamp=1000.0 + i * 10,
                volume=10.0,
            )
            for i in range(10)
        ]
        await storage.insert_ticks(ticks)

        # Query middle range: timestamps 1020 to 1060
        result = await storage.get_ticks("token_abc", start=1020.0, end=1060.0)
        assert len(result) == 5  # timestamps 1020, 1030, 1040, 1050, 1060

    @pytest.mark.asyncio
    async def test_query_only_start(self, storage):
        """Verify query with only start time."""
        ticks = [
            Tick(source="test", token_id="t1", price=1.0, timestamp=1000.0 + i)
            for i in range(10)
        ]
        await storage.insert_ticks(ticks)

        result = await storage.get_ticks("t1", start=1005.0)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_query_only_end(self, storage):
        """Verify query with only end time."""
        ticks = [
            Tick(source="test", token_id="t1", price=1.0, timestamp=1000.0 + i)
            for i in range(10)
        ]
        await storage.insert_ticks(ticks)

        result = await storage.get_ticks("t1", end=1004.0)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_empty_result_for_unknown_token(self, storage):
        """Verify empty result for unknown token_id."""
        result = await storage.get_ticks("nonexistent_token")
        assert result == []


class TestOrderBookSnapshots:
    """Tests for order book snapshot storage."""

    @pytest.mark.asyncio
    async def test_insert_and_retrieve_snapshot(self, storage):
        """Verify order book snapshot persistence."""
        snapshot = OrderBookSnapshot(
            timestamp=1000.0,
            token_id="token_abc",
            bids=((0.54, 100.0), (0.53, 200.0)),
            asks=((0.56, 150.0), (0.57, 250.0)),
        )
        await storage.insert_orderbook_snapshot(snapshot)

        result = await storage.get_orderbook_history("token_abc")
        assert len(result) == 1
        assert result[0].token_id == "token_abc"
        assert len(result[0].bids) == 2
        assert len(result[0].asks) == 2


class TestFills:
    """Tests for fill storage."""

    @pytest.mark.asyncio
    async def test_insert_and_retrieve_fill(self, storage):
        """Verify fill persistence."""
        fill = Fill(
            timestamp=1000.0,
            token_id="token_abc",
            price=0.55,
            size=100.0,
            side="buy",
            slippage=0.001,
        )
        await storage.insert_fill(fill)

        result = await storage.get_fills("token_abc")
        assert len(result) == 1
        assert result[0].price == 0.55
        assert result[0].side == "buy"
        assert result[0].slippage == 0.001


class TestOHLCV:
    """Tests for OHLCV aggregation."""

    @pytest.mark.asyncio
    async def test_ohlcv_aggregation(self, storage):
        """Verify OHLCV bar computation from ticks."""
        # Create ticks across 3 minute-bars
        ticks = []
        for i in range(30):
            ticks.append(Tick(
                source="test",
                token_id="t1",
                price=1.0 + (i % 10) * 0.1,
                timestamp=1000.0 + i * 10,
                volume=5.0,
            ))
        await storage.insert_ticks(ticks)

        bars = await storage.get_ohlcv("t1", interval_seconds=60.0)
        assert len(bars) >= 1
        # First bar should have correct OHLCV
        assert "open" in bars[0]
        assert "high" in bars[0]
        assert "low" in bars[0]
        assert "close" in bars[0]
        assert "volume" in bars[0]


class TestRecorder:
    """Tests for the TickRecorder class."""

    @pytest.mark.asyncio
    async def test_recorder_records_ticks(self, recorder):
        """Verify recorder persists ticks from an async stream."""
        ticks_to_send = [
            Tick(source="test", token_id="t1", price=0.5 + i * 0.01, timestamp=1000.0 + i)
            for i in range(10)
        ]

        async def tick_stream():
            for tick in ticks_to_send:
                yield tick
                await asyncio.sleep(0)

        await recorder.start_recording(tick_stream())
        # Give time for processing
        await asyncio.sleep(0.1)
        await recorder.stop_recording()

        result = await recorder.get_ticks("t1")
        assert len(result) == 10
        assert recorder.tick_count == 10

    @pytest.mark.asyncio
    async def test_recorder_export_csv(self, recorder):
        """Verify CSV export functionality."""
        await recorder.storage.initialize()
        ticks = [
            Tick(source="test", token_id="t1", price=0.5, timestamp=1000.0),
            Tick(source="test", token_id="t1", price=0.6, timestamp=1001.0),
        ]
        await recorder.storage.insert_ticks(ticks)

        csv_data = await recorder.export_csv("t1")
        assert "timestamp" in csv_data
        assert "0.5" in csv_data
        assert "0.6" in csv_data


class TestRetentionPolicy:
    """Tests for data retention policies."""

    @pytest.mark.asyncio
    async def test_retention_deletes_old_data(self, tmp_path):
        """Verify retention policy removes old records."""
        db_path = str(tmp_path / "retention.db")
        storage = StorageBackend(db_path=db_path, batch_size=10, retention_days=1)
        await storage.initialize()

        # Insert old ticks (2 days ago)
        old_ts = time.time() - 2 * 86400
        old_ticks = [
            Tick(source="test", token_id="t1", price=1.0, timestamp=old_ts + i)
            for i in range(5)
        ]
        await storage.insert_ticks(old_ticks)

        # Insert recent ticks
        recent_ts = time.time() - 3600
        recent_ticks = [
            Tick(source="test", token_id="t1", price=1.0, timestamp=recent_ts + i)
            for i in range(5)
        ]
        await storage.insert_ticks(recent_ticks)

        deleted = await storage.apply_retention_policy()
        assert deleted == 5

        # Recent ticks should remain
        remaining = await storage.get_ticks("t1")
        assert len(remaining) == 5

        await storage.close()


class TestModelSerialization:
    """Tests for data model serialization."""

    def test_tick_serialization(self):
        """Verify Tick to_dict/from_dict roundtrip."""
        tick = Tick(
            source="polymarket",
            token_id="abc",
            price=0.55,
            timestamp=1000.0,
            volume=100.0,
            bid=0.54,
            ask=0.56,
            sequence_number=42,
        )
        d = tick.to_dict()
        restored = Tick.from_dict(d)
        assert restored == tick

    def test_tick_json_roundtrip(self):
        """Verify Tick JSON serialization."""
        tick = Tick(source="test", token_id="t1", price=1.0, timestamp=100.0)
        json_str = tick.to_json()
        restored = Tick.from_json(json_str)
        assert restored == tick

    def test_orderbook_serialization(self):
        """Verify OrderBookSnapshot serialization."""
        snapshot = OrderBookSnapshot(
            timestamp=1000.0,
            token_id="abc",
            bids=((0.54, 100.0),),
            asks=((0.56, 150.0),),
        )
        d = snapshot.to_dict()
        restored = OrderBookSnapshot.from_dict(d)
        assert restored == snapshot

    def test_fill_serialization(self):
        """Verify Fill serialization."""
        fill = Fill(
            timestamp=1000.0,
            token_id="abc",
            price=0.55,
            size=100.0,
            side="buy",
            slippage=0.001,
        )
        d = fill.to_dict()
        restored = Fill.from_dict(d)
        assert restored == fill
