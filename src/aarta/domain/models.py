"""Immutable domain models for AARTA.

This module defines the core data structures used throughout AARTA:
- Instruments (tradable assets)
- Market data (bars, quotes)
- Order intents and sides
- Quantities and prices (using Decimal)
- Fills and executions
- Risk limits and decisions
- Order fingerprints for deduplication

All models are immutable dataclasses with explicit enums.
Timestamps are timezone-aware UTC.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Final
from zoneinfo import ZoneInfo

# =============================================================================
# CONSTANTS
# =============================================================================

UTC: Final[ZoneInfo] = ZoneInfo("UTC")


# =============================================================================
# ENUMS
# =============================================================================


class OrderSide(Enum):
    """Order side enumeration."""

    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type enumeration."""

    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(Enum):
    """Time-in-force enumeration."""

    DAY = "day"
    IOC = "ioc"  # Immediate-or-cancel


class OrderStatus(Enum):
    """Order status enumeration."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class RiskDecision(Enum):
    """Risk decision enumeration."""

    APPROVED = "approved"
    REJECTED = "rejected"


class RejectionReason(Enum):
    """Rejection reason enumeration."""

    LIVE_TRADING_DISABLED = "live_trading_disabled"
    EXCEEDS_POSITION_LIMIT = "exceeds_position_limit"
    EXCEEDS_CAPITAL_ALLOCATION = "exceeds_capital_allocation"
    INVALID_INSTRUMENT = "invalid_instrument"
    INVALID_PRICE = "invalid_price"
    INVALID_QUANTITY = "invalid_quantity"
    INSUFFICIENT_CAPITAL = "insufficient_capital"
    DUPLICATE_ORDER = "duplicate_order"
    MARKET_CLOSED = "market_closed"
    UNKNOWN = "unknown"


# =============================================================================
# INSTRUMENT MODELS
# =============================================================================


@dataclass(frozen=True)
class Instrument:
    """Represents a tradable instrument.

    Attributes:
        symbol: Unique symbol identifier (e.g., "NIFTYBEES").
        name: Human-readable name.
        exchange: Exchange identifier (e.g., "NSE").
        lot_size: Minimum tradable quantity (1 for cash market).
        tick_size: Minimum price increment.
        currency: Currency code (e.g., "INR").
        instrument_type: Type of instrument (e.g., "ETF", "INDEX", "STOCK").
    """

    symbol: str
    name: str
    exchange: str
    lot_size: int
    tick_size: Decimal
    currency: str
    instrument_type: str

    def __post_init__(self) -> None:
        """Validate instrument constraints."""
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")
        if self.tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if not self.symbol.strip():
            raise ValueError("symbol cannot be empty")
        if not self.exchange.strip():
            raise ValueError("exchange cannot be empty")

    @property
    def identity(self) -> str:
        """Compute SHA-256 identity of the instrument."""
        canonical = json.dumps(
            {
                "symbol": self.symbol,
                "name": self.name,
                "exchange": self.exchange,
                "lot_size": self.lot_size,
                "tick_size": str(self.tick_size),
                "currency": self.currency,
                "instrument_type": self.instrument_type,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# =============================================================================
# MARKET DATA MODELS
# =============================================================================


@dataclass(frozen=True)
class Bar:
    """OHLCV bar representing a time period.

    Attributes:
        instrument_id: SHA-256 identity of the instrument.
        timestamp: Start of bar period in UTC.
        open: Opening price.
        high: Highest price during period.
        low: Lowest price during period.
        close: Closing price.
        volume: Traded volume.
    """

    instrument_id: str
    timestamp: str  # ISO 8601 UTC string
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        """Validate bar constraints."""
        if self.low > self.high:
            raise ValueError("low cannot exceed high")
        if self.open < self.low or self.open > self.high:
            raise ValueError("open must be within [low, high]")
        if self.close < self.low or self.close > self.high:
            raise ValueError("close must be within [low, high]")
        if self.volume < 0:
            raise ValueError("volume cannot be negative")

    @property
    def identity(self) -> str:
        """Compute SHA-256 identity of the bar."""
        canonical = json.dumps(
            {
                "instrument_id": self.instrument_id,
                "timestamp": self.timestamp,
                "open": str(self.open),
                "high": str(self.high),
                "low": str(self.low),
                "close": str(self.close),
                "volume": self.volume,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Quote:
    """Bid/ask quote snapshot.

    Attributes:
        instrument_id: SHA-256 identity of the instrument.
        timestamp: Quote timestamp in UTC (ISO 8601 string).
        bid_price: Best bid price.
        ask_price: Best ask price.
        bid_size: Quantity at bid.
        ask_size: Quantity at ask.
    """

    instrument_id: str
    timestamp: str
    bid_price: Decimal
    ask_price: Decimal
    bid_size: int
    ask_size: int

    def __post_init__(self) -> None:
        """Validate quote constraints."""
        if self.bid_price >= self.ask_price:
            raise ValueError("bid_price must be less than ask_price")
        if self.bid_size <= 0 or self.ask_size <= 0:
            raise ValueError("sizes must be positive")


# =============================================================================
# ORDER MODELS
# =============================================================================


@dataclass(frozen=True)
class OrderIntent:
    """An order intent proposed by a strategy.

    This is NOT an actual order - it must be approved by the risk authority.

    Attributes:
        strategy_id: ID of the strategy proposing this intent.
        instrument_id: SHA-256 identity of the instrument.
        side: Buy or sell.
        order_type: Market or limit.
        quantity: Number of units to trade.
        limit_price: Limit price (required for LIMIT orders).
        time_in_force: Day or IOC.
        client_order_id: Client-supplied order ID for deduplication.
        timestamp: Intent creation timestamp in UTC.
    """

    strategy_id: str
    instrument_id: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: Decimal | None
    time_in_force: TimeInForce
    client_order_id: str
    timestamp: str

    def __post_init__(self) -> None:
        """Validate order intent constraints."""
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price required for LIMIT orders")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("limit_price not allowed for MARKET orders")

    @property
    def fingerprint(self) -> str:
        """Compute SHA-256 fingerprint for deduplication."""
        canonical = json.dumps(
            {
                "strategy_id": self.strategy_id,
                "instrument_id": self.instrument_id,
                "side": self.side.value,
                "order_type": self.order_type.value,
                "quantity": self.quantity,
                "limit_price": str(self.limit_price) if self.limit_price else None,
                "time_in_force": self.time_in_force.value,
                "client_order_id": self.client_order_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Order:
    """An order submitted to the execution system.

    Attributes:
        order_id: System-generated unique order ID (SHA-256).
        intent: The original order intent.
        status: Current order status.
        submitted_at: Submission timestamp in UTC.
    """

    order_id: str
    intent: OrderIntent
    status: OrderStatus
    submitted_at: str


# =============================================================================
# FILL MODELS
# =============================================================================


@dataclass(frozen=True)
class Fill:
    """A fill resulting from order execution.

    Attributes:
        fill_id: Unique fill identifier (SHA-256).
        order_id: Parent order ID.
        instrument_id: Instrument being traded.
        side: Buy or sell.
        quantity: Filled quantity.
        price: Fill price.
        fee: Transaction fee (always non-negative).
        timestamp: Fill timestamp in UTC.
    """

    fill_id: str
    order_id: str
    instrument_id: str
    side: OrderSide
    quantity: int
    price: Decimal
    fee: Decimal
    timestamp: str

    def __post_init__(self) -> None:
        """Validate fill constraints."""
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.price <= 0:
            raise ValueError("price must be positive")
        if self.fee < 0:
            raise ValueError("fee cannot be negative")

    @property
    def net_amount(self) -> Decimal:
        """Calculate net amount (quantity * price + fee)."""
        base = Decimal(self.quantity) * self.price
        return base + self.fee


# =============================================================================
# RISK MODELS
# =============================================================================


@dataclass(frozen=True)
class RiskLimits:
    """Risk limits imposed by the risk authority.

    Attributes:
        max_position_value: Maximum total position value in currency units.
        max_order_value: Maximum single order value.
        max_daily_turnover: Maximum daily trading turnover.
        max_open_positions: Maximum number of concurrent open positions.
        allowed_instruments: Set of allowed instrument IDs (empty = all allowed).
    """

    max_position_value: Decimal
    max_order_value: Decimal
    max_daily_turnover: Decimal
    max_open_positions: int
    allowed_instruments: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        """Validate risk limit constraints."""
        if self.max_position_value <= 0:
            raise ValueError("max_position_value must be positive")
        if self.max_order_value <= 0:
            raise ValueError("max_order_value must be positive")
        if self.max_daily_turnover <= 0:
            raise ValueError("max_daily_turnover must be positive")
        if self.max_open_positions <= 0:
            raise ValueError("max_open_positions must be positive")


@dataclass(frozen=True)
class RiskDecisionResult:
    """Result of risk evaluation.

    Attributes:
        decision: APPROVED or REJECTED.
        reason: Rejection reason (if rejected).
        details: Additional context about the decision.
    """

    decision: RiskDecision
    reason: RejectionReason | None
    details: str

    def __post_init__(self) -> None:
        """Validate decision constraints."""
        if self.decision == RiskDecision.REJECTED and self.reason is None:
            raise ValueError("reason required when decision is REJECTED")
        if self.decision == RiskDecision.APPROVED and self.reason is not None:
            raise ValueError("reason must be None when decision is APPROVED")
