"""Unit tests for the 6-layer websocket system.

Tests cover:
- Connection jitter tracking
- First-tick skip (Layer 4)
- Stale tick rejection (Layer 3)
- Warmup quality gate logic (Layer 1)
- Deduplication
- Respawn budget enforcement (Layer 6)
- Staggered startup (Layer 5)
- Dynamic spawning (Layer 2)
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from polymarket_bot.feeds.base import Tick
from polymarket_bot.websocket.connection import WebSocketConnection
from polymarket_bot.websocket.guards import JitterReaper, StaleTickGuard
from polymarket_bot.websocket.manager import WebSocketManager
from polymarket_bot.websocket.pool import ConnectionPool
from polymarket_bot.websocket.warmup import WarmupManager


# --- Helpers ---

def make_tick(
    price: float = 0.50,
    token_id: str = "token_a",
    source: str = "test",
    timestamp: float = 0.0,
    volume: float = 1.0,
    sequence: int = 1,
) -> Tick:
    """Create a test Tick with defaults."""
    return Tick(
        source=source,
        token_id=token_id,
        price=price,
        timestamp=timestamp or time.time(),
        volume=volume,
        bid=price - 0.01,
        ask=price + 0.01,
        sequence_number=sequence,
    )


# --- Layer 4: First-tick skip tests ---

class TestFirstTickSkip:
    """Tests for Layer 4: first-tick skip on connections."""

    def test_first_tick_is_skipped(self):
        """The very first tick from a connection should be dropped."""
        conn = WebSocketConnection(url="wss://test.example.com")
        tick = make_tick(price=0.50, timestamp=time.time())

        result = conn.process_tick(tick)
        assert result is None, "First tick should be skipped (None)"

    def test_second_tick_passes(self):
        """The second tick and beyond should pass through."""
        conn = WebSocketConnection(url="wss://test.example.com")
        t1 = make_tick(price=0.50, timestamp=time.time())
        t2 = make_tick(price=0.51, timestamp=time.time() + 0.1, sequence=2)

        conn.process_tick(t1)  # skipped
        result = conn.process_tick(t2)
        assert result is not None
        assert result.price == 0.51

    def test_tick_count_increments_including_skipped(self):
        """Tick count should include the skipped first tick."""
        conn = WebSocketConnection(url="wss://test.example.com")
        t = time.time()
        conn.process_tick(make_tick(timestamp=t))
        conn.process_tick(make_tick(timestamp=t + 0.1, sequence=2))
        conn.process_tick(make_tick(timestamp=t + 0.2, sequence=3))

        assert conn.tick_count == 3


# --- Connection jitter tracking tests ---

class TestJitterTracking:
    """Tests for connection jitter EMA tracking."""

    def test_jitter_ema_starts_at_zero(self):
        """New connection should have zero jitter EMA."""
        conn = WebSocketConnection(url="wss://test.example.com")
        assert conn.jitter_ema == 0.0

    def test_jitter_ema_updates_on_tick(self):
        """Jitter EMA should update after processing ticks with varying intervals."""
        conn = WebSocketConnection(url="wss://test.example.com")
        t = time.time()

        conn.process_tick(make_tick(timestamp=t))  # first tick (skipped)
        conn.process_tick(make_tick(timestamp=t + 0.1, sequence=2))  # establishes baseline
        conn.process_tick(make_tick(timestamp=t + 0.3, sequence=3))  # different interval

        assert conn.jitter_ema > 0.0

    def test_jitter_ema_increases_with_irregular_intervals(self):
        """Jitter EMA should reflect irregular tick intervals."""
        conn = WebSocketConnection(url="wss://test.example.com")
        t = time.time()

        conn.process_tick(make_tick(timestamp=t))
        conn.process_tick(make_tick(timestamp=t + 0.01, sequence=2))  # 10ms
        jitter_after_small = conn.jitter_ema

        conn.process_tick(make_tick(timestamp=t + 1.01, sequence=3))  # 1000ms gap
        jitter_after_large = conn.jitter_ema

        assert jitter_after_large > jitter_after_small

    def test_grace_period_active_for_new_connection(self):
        """New connections should be in grace period."""
        conn = WebSocketConnection(url="wss://test.example.com")
        assert conn.is_in_grace_period is True

    def test_grace_period_expires(self):
        """Grace period should expire after GRACE_PERIOD_SECONDS."""
        conn = WebSocketConnection(url="wss://test.example.com")
        conn.created_at = time.time() - 10.0  # 10 seconds ago
        assert conn.is_in_grace_period is False


# --- Layer 3: Stale tick guard tests ---

class TestStaleTickGuard:
    """Tests for Layer 3: stale tick rejection."""

    def test_tick_within_threshold_passes(self):
        """Ticks with delta <= 15c from warmup should pass."""
        guard = StaleTickGuard(warmup_prices={"token_a": 0.50})
        tick = make_tick(price=0.55, token_id="token_a")

        assert guard.check(tick) is True

    def test_tick_at_boundary_passes(self):
        """Tick just under 15c delta should pass."""
        guard = StaleTickGuard(warmup_prices={"token_a": 0.50})
        tick = make_tick(price=0.64, token_id="token_a")  # 14c delta

        assert guard.check(tick) is True

    def test_tick_exceeding_threshold_rejected(self):
        """Ticks with delta > 15c from warmup should be rejected."""
        guard = StaleTickGuard(warmup_prices={"token_a": 0.50})
        tick = make_tick(price=0.70, token_id="token_a")  # 20c delta

        assert guard.check(tick) is False

    def test_tick_below_warmup_rejected(self):
        """Ticks below warmup by >15c should also be rejected."""
        guard = StaleTickGuard(warmup_prices={"token_a": 0.50})
        tick = make_tick(price=0.30, token_id="token_a")  # 20c below

        assert guard.check(tick) is False

    def test_unknown_token_passes(self):
        """Ticks for tokens without warmup price should pass."""
        guard = StaleTickGuard(warmup_prices={"token_a": 0.50})
        tick = make_tick(price=0.99, token_id="token_unknown")

        assert guard.check(tick) is True

    def test_rejected_count_tracking(self):
        """Guard should track rejection count."""
        guard = StaleTickGuard(warmup_prices={"token_a": 0.50})

        guard.check(make_tick(price=0.70, token_id="token_a"))  # rejected
        guard.check(make_tick(price=0.80, token_id="token_a"))  # rejected
        guard.check(make_tick(price=0.52, token_id="token_a"))  # accepted

        assert guard.rejected_count == 2
        assert guard.accepted_count == 1


# --- Layer 1: Warmup quality gate tests ---

class TestWarmupQualityGate:
    """Tests for Layer 1: warmup with quality gate."""

    def test_warmup_passes_with_enough_ticks_no_jumps(self):
        """Quality gate passes with 3+ ticks and no >5c jumps."""
        warmup = WarmupManager(token_ids=["token_a"])
        warmup.start()
        # Simulate being in the quality gate window
        warmup._gate_active = True

        warmup.process_tick(make_tick(price=0.50, token_id="token_a"))
        warmup.process_tick(make_tick(price=0.51, token_id="token_a"))
        warmup.process_tick(make_tick(price=0.52, token_id="token_a"))

        assert warmup.check_quality_gate() is True

    def test_warmup_fails_with_too_few_ticks(self):
        """Quality gate fails with < 3 ticks."""
        warmup = WarmupManager(token_ids=["token_a"])
        warmup.start()
        warmup._gate_active = True

        warmup.process_tick(make_tick(price=0.50, token_id="token_a"))
        warmup.process_tick(make_tick(price=0.51, token_id="token_a"))

        assert warmup.check_quality_gate() is False

    def test_warmup_fails_with_large_price_jump(self):
        """Quality gate fails if any single jump > 5 cents."""
        warmup = WarmupManager(token_ids=["token_a"])
        warmup.start()
        warmup._gate_active = True

        warmup.process_tick(make_tick(price=0.50, token_id="token_a"))
        warmup.process_tick(make_tick(price=0.56, token_id="token_a"))  # 6c jump
        warmup.process_tick(make_tick(price=0.57, token_id="token_a"))

        assert warmup.check_quality_gate() is False

    def test_warmup_tracks_prices_per_token(self):
        """Warmup should track last price per token."""
        warmup = WarmupManager(token_ids=["token_a", "token_b"])
        warmup.start()
        warmup._gate_active = True

        warmup.process_tick(make_tick(price=0.50, token_id="token_a"))
        warmup.process_tick(make_tick(price=0.60, token_id="token_b"))

        assert warmup.warmup_prices["token_a"] == 0.50
        assert warmup.warmup_prices["token_b"] == 0.60

    def test_warmup_ticks_before_gate_not_counted(self):
        """Ticks received before the quality gate window should not count."""
        warmup = WarmupManager(token_ids=["token_a"])
        warmup.start()
        # Gate not active yet
        warmup._gate_active = False

        warmup.process_tick(make_tick(price=0.50, token_id="token_a"))
        warmup.process_tick(make_tick(price=0.51, token_id="token_a"))
        warmup.process_tick(make_tick(price=0.52, token_id="token_a"))

        # Now activate gate - no ticks counted yet
        warmup._gate_active = True
        # Only 0 ticks in gate window
        assert warmup.check_quality_gate() is False

    def test_warmup_passes_with_jump_under_5c(self):
        """Jumps under 5c should pass."""
        warmup = WarmupManager(token_ids=["token_a"])
        warmup.start()
        warmup._gate_active = True

        warmup.process_tick(make_tick(price=0.50, token_id="token_a"))
        warmup.process_tick(make_tick(price=0.54, token_id="token_a"))  # 4c jump
        warmup.process_tick(make_tick(price=0.56, token_id="token_a"))  # 2c jump

        assert warmup.check_quality_gate() is True

    def test_warmup_multiple_tokens_partial_fail(self):
        """If one token fails, the whole gate fails."""
        warmup = WarmupManager(token_ids=["token_a", "token_b"])
        warmup.start()
        warmup._gate_active = True

        # token_a: 3 ticks, no jumps - passes
        warmup.process_tick(make_tick(price=0.50, token_id="token_a"))
        warmup.process_tick(make_tick(price=0.51, token_id="token_a"))
        warmup.process_tick(make_tick(price=0.52, token_id="token_a"))

        # token_b: only 2 ticks - fails
        warmup.process_tick(make_tick(price=0.60, token_id="token_b"))
        warmup.process_tick(make_tick(price=0.61, token_id="token_b"))

        assert warmup.check_quality_gate() is False


# --- Deduplication tests ---

class TestDeduplication:
    """Tests for tick deduplication by content hash."""

    def test_duplicate_tick_detected(self):
        """Same tick sent twice should be detected as duplicate."""
        pool = ConnectionPool(url="wss://test.example.com", min_connections=1)
        tick = make_tick(price=0.50, timestamp=1000.0, sequence=1)

        assert pool.is_duplicate(tick) is False  # First time
        assert pool.is_duplicate(tick) is True  # Duplicate

    def test_different_ticks_not_duplicate(self):
        """Different ticks should not be flagged as duplicates."""
        pool = ConnectionPool(url="wss://test.example.com", min_connections=1)
        tick1 = make_tick(price=0.50, timestamp=1000.0, sequence=1)
        tick2 = make_tick(price=0.51, timestamp=1000.1, sequence=2)

        assert pool.is_duplicate(tick1) is False
        assert pool.is_duplicate(tick2) is False

    def test_same_price_different_timestamp_not_duplicate(self):
        """Same price but different timestamp is a new tick."""
        pool = ConnectionPool(url="wss://test.example.com", min_connections=1)
        tick1 = make_tick(price=0.50, timestamp=1000.0, sequence=1)
        tick2 = make_tick(price=0.50, timestamp=1000.1, sequence=2)

        assert pool.is_duplicate(tick1) is False
        assert pool.is_duplicate(tick2) is False


# --- Layer 6: Jitter reaper tests ---

class TestJitterReaper:
    """Tests for Layer 6: anti-jitter reaper."""

    def test_grace_period_respected(self):
        """Connections in grace period should not be culled."""
        reaper = JitterReaper()

        # Create connections all in grace period
        connections = []
        for i in range(5):
            conn = WebSocketConnection(url="wss://test.example.com")
            conn.jitter_ema = 100.0 * (i + 1)  # High jitter
            # created_at is now, so in grace period
            connections.append(conn)

        candidates = reaper.get_cull_candidates(connections)
        assert len(candidates) == 0, "Connections in grace period should not be culled"

    def test_worst_jitter_culled_first(self):
        """Connections with highest jitter EMA should be culled first."""
        reaper = JitterReaper()

        connections = []
        for i in range(5):
            conn = WebSocketConnection(url="wss://test.example.com")
            conn.jitter_ema = 10.0 * (i + 1)
            conn.created_at = time.time() - 20.0  # Past grace period
            connections.append(conn)

        candidates = reaper.get_cull_candidates(connections)
        assert len(candidates) > 0
        # First candidate should have highest jitter
        assert candidates[0].jitter_ema == 50.0

    def test_max_culls_per_cycle(self):
        """Should not cull more than MAX_CULLS_PER_CYCLE per call."""
        reaper = JitterReaper()

        connections = []
        for i in range(10):
            conn = WebSocketConnection(url="wss://test.example.com")
            conn.jitter_ema = 100.0 * (i + 1)
            conn.created_at = time.time() - 20.0  # Past grace
            connections.append(conn)

        candidates = reaper.get_cull_candidates(connections)
        assert len(candidates) <= JitterReaper.MAX_CULLS_PER_CYCLE

    def test_budget_enforcement(self):
        """Should respect the 20 respawns/minute budget."""
        reaper = JitterReaper()

        # Exhaust the budget
        now = time.time()
        reaper._respawn_timestamps = [now - i for i in range(20)]

        connections = []
        for i in range(5):
            conn = WebSocketConnection(url="wss://test.example.com")
            conn.jitter_ema = 100.0
            conn.created_at = time.time() - 20.0
            connections.append(conn)

        candidates = reaper.get_cull_candidates(connections)
        assert len(candidates) == 0, "Should not cull when budget is exhausted"

    def test_budget_recovers_over_time(self):
        """Budget should recover as old respawns age out past 60s."""
        reaper = JitterReaper()

        # Add respawns from 61+ seconds ago (should not count)
        reaper._respawn_timestamps = [time.time() - 70.0 for _ in range(20)]

        assert reaper.budget_remaining == 20

    def test_record_cull_updates_budget(self):
        """Recording a cull should reduce remaining budget."""
        reaper = JitterReaper()
        initial_budget = reaper.budget_remaining

        reaper.record_cull(count=3)
        assert reaper.budget_remaining == initial_budget - 3


# --- Layer 5: Staggered startup tests ---

class TestStaggeredStartup:
    """Tests for Layer 5: staggered startup."""

    @pytest.mark.asyncio
    async def test_connections_created_with_stagger(self):
        """Pool should create connections with staggered delays."""
        pool = ConnectionPool(
            url="wss://test.example.com",
            min_connections=5,
            max_connections=10,
        )
        # Override stagger window for fast test
        pool.STAGGER_WINDOW_S = 0.05

        await pool.start()

        assert pool.active_count == 5
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_stop_clears_connections(self):
        """Stopping pool should clear all connections."""
        pool = ConnectionPool(
            url="wss://test.example.com",
            min_connections=3,
            max_connections=10,
        )
        pool.STAGGER_WINDOW_S = 0.01

        await pool.start()
        assert pool.active_count == 3

        await pool.stop()
        assert pool.active_count == 0


# --- Layer 2: Dynamic spawning tests ---

class TestDynamicSpawning:
    """Tests for Layer 2: dynamic spawning of connections."""

    @pytest.mark.asyncio
    async def test_respawn_slowest_removes_and_replaces(self):
        """Respawning should remove slowest and add new connections."""
        pool = ConnectionPool(
            url="wss://test.example.com",
            min_connections=10,
            max_connections=20,
        )
        pool.STAGGER_WINDOW_S = 0.01
        await pool.start()

        # Set jitter values - make some connections old enough
        for i, conn in enumerate(pool.connections):
            conn.jitter_ema = float(i * 10)
            conn.created_at = time.time() - 20.0  # Past grace

        initial_count = pool.active_count
        new_conns = await pool.respawn_slowest()

        # Should have same total count
        assert pool.active_count == initial_count
        # Should have new connections
        assert len(new_conns) > 0
        # New connections should be in grace period
        for nc in new_conns:
            assert nc.is_in_grace_period

        await pool.stop()

    def test_get_slowest_excludes_grace_period(self):
        """Slowest calculation should exclude connections in grace period."""
        pool = ConnectionPool(url="wss://test.example.com", min_connections=5)

        # Manually add connections
        for i in range(5):
            conn = WebSocketConnection(url="wss://test.example.com")
            conn.jitter_ema = float(i * 50)
            if i < 3:
                conn.created_at = time.time() - 20.0  # Past grace
            # i >= 3 are in grace period (created just now)
            pool._connections.append(conn)

        slowest = pool.get_slowest_connections()
        # Only connections past grace should be eligible
        for s in slowest:
            assert not s.is_in_grace_period


# --- Manager integration tests ---

class TestWebSocketManager:
    """Integration tests for the WebSocket manager."""

    @pytest.mark.asyncio
    async def test_manager_start_stop(self):
        """Manager should start and stop cleanly."""
        manager = WebSocketManager(
            url="wss://test.example.com",
            num_connections=3,
            max_connections=5,
        )
        manager._pool.STAGGER_WINDOW_S = 0.01

        result = await manager.start(token_ids=["token_a"])
        assert result is True
        assert manager.is_running is True

        await manager.stop()
        assert manager.is_running is False

    @pytest.mark.asyncio
    async def test_process_tick_during_warmup(self):
        """Ticks during warmup should be fed to warmup manager."""
        manager = WebSocketManager(
            url="wss://test.example.com",
            num_connections=2,
            max_connections=5,
        )
        manager._pool.STAGGER_WINDOW_S = 0.01
        await manager.start(token_ids=["token_a"])

        conn = WebSocketConnection(url="wss://test.example.com")
        tick = make_tick(price=0.50, token_id="token_a")

        # During warmup, first tick is skipped (Layer 4)
        result = manager.process_tick(tick, conn)
        assert result is None  # First tick skipped

        await manager.stop()

    @pytest.mark.asyncio
    async def test_process_tick_after_warmup(self):
        """After warmup, ticks should pass through all layers."""
        manager = WebSocketManager(
            url="wss://test.example.com",
            num_connections=2,
            max_connections=5,
        )
        manager._pool.STAGGER_WINDOW_S = 0.01
        await manager.start(token_ids=["token_a"])

        # Complete warmup with good data
        manager._warmup._gate_active = True
        for i in range(3):
            manager._warmup.process_tick(
                make_tick(price=0.50 + i * 0.01, token_id="token_a")
            )
        await manager.complete_warmup()

        # Now process ticks - first is skipped
        conn = WebSocketConnection(url="wss://test.example.com")
        t = time.time()
        tick1 = make_tick(price=0.51, token_id="token_a", timestamp=t)
        tick2 = make_tick(price=0.52, token_id="token_a", timestamp=t + 0.1, sequence=2)

        result1 = manager.process_tick(tick1, conn)
        assert result1 is None  # First tick skip

        result2 = manager.process_tick(tick2, conn)
        assert result2 is not None
        assert result2.price == 0.52

        await manager.stop()

    @pytest.mark.asyncio
    async def test_stale_tick_rejected_after_warmup(self):
        """After warmup, stale ticks (>15c delta) should be rejected."""
        manager = WebSocketManager(
            url="wss://test.example.com",
            num_connections=2,
            max_connections=5,
        )
        manager._pool.STAGGER_WINDOW_S = 0.01
        await manager.start(token_ids=["token_a"])

        # Complete warmup
        manager._warmup._gate_active = True
        for i in range(3):
            manager._warmup.process_tick(
                make_tick(price=0.50 + i * 0.01, token_id="token_a")
            )
        await manager.complete_warmup()

        conn = WebSocketConnection(url="wss://test.example.com")
        t = time.time()
        # First tick skipped
        conn.process_tick(make_tick(price=0.50, timestamp=t))

        # Stale tick (>15c from warmup price of ~0.52)
        stale_tick = make_tick(price=0.80, token_id="token_a", timestamp=t + 0.1, sequence=2)
        result = manager.process_tick(stale_tick, conn)
        assert result is None  # Rejected by stale guard

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Manager should provide comprehensive stats."""
        manager = WebSocketManager(
            url="wss://test.example.com",
            num_connections=2,
            max_connections=5,
        )
        manager._pool.STAGGER_WINDOW_S = 0.01
        await manager.start(token_ids=["token_a"])

        stats = manager.get_stats()
        assert "running" in stats
        assert "pool" in stats
        assert "stale_guard" in stats
        assert "jitter_reaper" in stats
        assert stats["running"] is True

        await manager.stop()


# --- Tick dataclass tests ---

class TestTickDataclass:
    """Tests for the Tick dataclass."""

    def test_tick_fields(self):
        """Tick should have all required fields."""
        tick = Tick(
            source="test",
            token_id="abc",
            price=0.55,
            timestamp=1000.0,
            volume=10.0,
            bid=0.54,
            ask=0.56,
            sequence_number=42,
        )
        assert tick.source == "test"
        assert tick.token_id == "abc"
        assert tick.price == 0.55
        assert tick.timestamp == 1000.0
        assert tick.volume == 10.0
        assert tick.bid == 0.54
        assert tick.ask == 0.56
        assert tick.sequence_number == 42

    def test_tick_content_hash_consistent(self):
        """Same tick should produce same hash."""
        tick = make_tick(price=0.50, timestamp=1000.0, sequence=1)
        assert tick.content_hash() == tick.content_hash()

    def test_different_ticks_different_hash(self):
        """Different ticks should produce different hashes."""
        tick1 = make_tick(price=0.50, timestamp=1000.0, sequence=1)
        tick2 = make_tick(price=0.51, timestamp=1000.0, sequence=2)
        assert tick1.content_hash() != tick2.content_hash()

    def test_tick_is_frozen(self):
        """Tick should be immutable (frozen dataclass)."""
        tick = make_tick()
        with pytest.raises(Exception):
            tick.price = 0.99  # type: ignore[misc]
