"""WebSocket connection management and data streaming.

6-layer websocket system:
    Layer 1: Warmup (15s pre-trade, 5s quality gate)
    Layer 2: Dynamic spawning (kill/respawn slowest 10% every 4s)
    Layer 3: Stale tick guard (reject >15c delta from warmup)
    Layer 4: First-tick skip (drop first tick per connection)
    Layer 5: Staggered startup (spread connections over 1s)
    Layer 6: Anti-jitter reaper (EMA tracking, grace period, budget)
"""

from polymarket_bot.websocket.connection import WebSocketConnection
from polymarket_bot.websocket.guards import JitterReaper, StaleTickGuard
from polymarket_bot.websocket.manager import WebSocketManager
from polymarket_bot.websocket.pool import ConnectionPool
from polymarket_bot.websocket.warmup import WarmupManager

__all__ = [
    "WebSocketConnection",
    "WebSocketManager",
    "ConnectionPool",
    "WarmupManager",
    "StaleTickGuard",
    "JitterReaper",
]
