"""
Polymarket API Client
=====================
Handles all interactions with the Polymarket APIs:
- Gamma API: Market discovery & metadata
- CLOB API: Orderbook, pricing, order placement
- Data API: Positions, trades, portfolio data
"""

import time
import requests
from typing import Optional
from loguru import logger

from py_clob_client_v2 import ClobClient, ApiCreds, OrderArgs, PartialCreateOrderOptions
from py_clob_client_v2.order_builder.constants import BUY, SELL
from py_clob_client_v2 import OrderType

from config import Config


class PolymarketClient:
    """Unified client for all Polymarket API interactions."""

    def __init__(self, config: Config):
        self.config = config
        self.clob_client: Optional[ClobClient] = None
        self._initialize_client()

    def _initialize_client(self):
        """Initialize the CLOB client with authentication."""
        try:
            # First, derive or use existing API credentials
            if self.config.wallet.api_key:
                creds = ApiCreds(
                    api_key=self.config.wallet.api_key,
                    api_secret=self.config.wallet.api_secret,
                    api_passphrase=self.config.wallet.api_passphrase,
                )
            else:
                # Derive credentials from private key
                temp_client = ClobClient(
                    host=self.config.api.clob_url,
                    key=self.config.wallet.private_key,
                    chain_id=self.config.api.chain_id,
                )
                creds_response = temp_client.create_or_derive_api_key()
                creds = ApiCreds(
                    api_key=creds_response["apiKey"],
                    api_secret=creds_response["secret"],
                    api_passphrase=creds_response["passphrase"],
                )
                logger.info(f"Derived API credentials: key={creds_response['apiKey'][:8]}...")

            # Initialize full trading client
            self.clob_client = ClobClient(
                host=self.config.api.clob_url,
                key=self.config.wallet.private_key,
                chain_id=self.config.api.chain_id,
                creds=creds,
                signature_type=self.config.wallet.signature_type,
                funder=self.config.wallet.deposit_wallet_address,
            )
            logger.info("CLOB client initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {e}")
            raise

    # =========================================================================
    # MARKET DATA (Gamma API - Public, No Auth)
    # =========================================================================

    def get_active_markets(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """Fetch active markets from the Gamma API."""
        try:
            response = requests.get(
                f"{self.config.api.gamma_url}/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": limit,
                    "offset": offset,
                },
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []

    def get_active_events(self, limit: int = 100, order: str = "volume_24hr") -> list[dict]:
        """Fetch active events ordered by volume."""
        try:
            response = requests.get(
                f"{self.config.api.gamma_url}/events",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": limit,
                    "order": order,
                    "ascending": "false",
                },
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching events: {e}")
            return []

    def get_market_by_id(self, market_id: str) -> Optional[dict]:
        """Fetch a specific market by condition ID."""
        try:
            response = requests.get(
                f"{self.config.api.gamma_url}/markets/{market_id}",
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching market {market_id}: {e}")
            return None

    # =========================================================================
    # ORDERBOOK & PRICING (CLOB API - Public, No Auth)
    # =========================================================================

    def get_orderbook(self, token_id: str) -> Optional[dict]:
        """Get the orderbook for a specific token."""
        try:
            return self.clob_client.get_order_book(token_id)
        except Exception as e:
            logger.error(f"Error fetching orderbook for {token_id[:16]}...: {e}")
            return None

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get the midpoint price for a token."""
        try:
            response = self.clob_client.get_midpoint(token_id)
            return float(response.get("mid", 0))
        except Exception as e:
            logger.error(f"Error fetching midpoint for {token_id[:16]}...: {e}")
            return None

    def get_price(self, token_id: str, side: str = "BUY") -> Optional[float]:
        """Get the best price for a given side."""
        try:
            response = self.clob_client.get_price(token_id, side)
            return float(response.get("price", 0))
        except Exception as e:
            logger.error(f"Error fetching price for {token_id[:16]}...: {e}")
            return None

    def get_spread(self, token_id: str) -> Optional[float]:
        """Get the bid-ask spread for a token."""
        try:
            response = self.clob_client.get_spread(token_id)
            return float(response.get("spread", 0))
        except Exception as e:
            logger.error(f"Error fetching spread for {token_id[:16]}...: {e}")
            return None

    def get_prices_history(self, token_id: str, interval: str = "1d") -> list[dict]:
        """Get historical price data."""
        try:
            return self.clob_client.get_prices_history(
                market=token_id,
                interval=interval,
            )
        except Exception as e:
            logger.error(f"Error fetching price history: {e}")
            return []

    # =========================================================================
    # TRADING (CLOB API - Authenticated)
    # =========================================================================

    def place_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
        tick_size: str = "0.01",
        neg_risk: bool = False,
    ) -> Optional[dict]:
        """Place a limit order."""
        try:
            order_side = BUY if side.upper() == "BUY" else SELL
            response = self.clob_client.create_and_post_order(
                OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=order_side,
                ),
                options=PartialCreateOrderOptions(
                    tick_size=tick_size,
                    neg_risk=neg_risk,
                ),
                order_type=OrderType.GTC,
            )
            logger.info(
                f"Order placed: {side} {size}@{price} on {token_id[:16]}... "
                f"-> ID: {response.get('orderID', 'N/A')}"
            )
            return response
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    def place_market_order(
        self,
        token_id: str,
        side: str,
        amount: float,
        price: float = None,
        tick_size: str = "0.01",
        neg_risk: bool = False,
    ) -> Optional[dict]:
        """Place a market order (FOK)."""
        try:
            from py_clob_client_v2 import MarketOrderArgs

            order_side = BUY if side.upper() == "BUY" else SELL
            response = self.clob_client.create_and_post_market_order(
                order_args=MarketOrderArgs(
                    token_id=token_id,
                    side=order_side,
                    amount=amount,
                    price=price,
                ),
                options=PartialCreateOrderOptions(
                    tick_size=tick_size,
                    neg_risk=neg_risk,
                ),
                order_type=OrderType.FOK,
            )
            logger.info(
                f"Market order placed: {side} ${amount} on {token_id[:16]}... "
                f"-> ID: {response.get('orderID', 'N/A')}"
            )
            return response
        except Exception as e:
            logger.error(f"Error placing market order: {e}")
            return None

    def cancel_order(self, order_id: str) -> Optional[dict]:
        """Cancel a specific order."""
        try:
            response = self.clob_client.cancel(order_id=order_id)
            logger.info(f"Order cancelled: {order_id}")
            return response
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return None

    def cancel_all_orders(self) -> Optional[dict]:
        """Cancel all open orders."""
        try:
            response = self.clob_client.cancel_all()
            logger.info("All orders cancelled")
            return response
        except Exception as e:
            logger.error(f"Error cancelling all orders: {e}")
            return None

    def get_open_orders(self, market: str = None) -> list[dict]:
        """Get all open orders, optionally filtered by market."""
        try:
            if market:
                from py_clob_client_v2 import OpenOrderParams
                return self.clob_client.get_orders(OpenOrderParams(market=market))
            return self.clob_client.get_orders()
        except Exception as e:
            logger.error(f"Error fetching open orders: {e}")
            return []

    def get_trades(self, market: str = None) -> list[dict]:
        """Get trade history."""
        try:
            if market:
                from py_clob_client_v2 import TradeParams
                return self.clob_client.get_trades(TradeParams(market=market))
            return self.clob_client.get_trades()
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
            return []

    # =========================================================================
    # PORTFOLIO DATA (Data API)
    # =========================================================================

    def get_positions(self, address: str = None) -> list[dict]:
        """Get current positions for a wallet address."""
        if not address:
            address = self.config.wallet.deposit_wallet_address
        try:
            response = requests.get(
                f"{self.config.api.data_url}/positions",
                params={"user": address},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def get_portfolio_value(self, address: str = None) -> float:
        """Get total portfolio value."""
        if not address:
            address = self.config.wallet.deposit_wallet_address
        try:
            response = requests.get(
                f"{self.config.api.data_url}/value",
                params={"user": address},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return float(data.get("value", 0))
        except Exception as e:
            logger.error(f"Error fetching portfolio value: {e}")
            return 0.0

    # =========================================================================
    # MARKET ANALYSIS HELPERS
    # =========================================================================

    def get_tick_size(self, token_id: str) -> str:
        """Get the tick size for a market."""
        try:
            return self.clob_client.get_tick_size(token_id)
        except Exception as e:
            logger.warning(f"Error fetching tick size, defaulting to 0.01: {e}")
            return "0.01"

    def get_neg_risk(self, token_id: str) -> bool:
        """Check if a market uses negative risk."""
        try:
            return self.clob_client.get_neg_risk(token_id)
        except Exception as e:
            logger.warning(f"Error fetching neg risk, defaulting to False: {e}")
            return False
