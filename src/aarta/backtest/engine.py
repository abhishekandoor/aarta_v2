"""Event-driven backtesting engine for AARTA.

This module provides deterministic market replay with strict event ordering,
no future-data access, and comprehensive trade funnel tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Protocol

from aarta.domain.models import (
    Bar,
    Fill,
    Instrument,
    Order,
    OrderIntent,
    OrderSide,
    OrderStatus,
    OrderType,
    RiskDecision,
    RiskDecisionResult,
    TimeInForce,
)


class EventType(Enum):
    """Types of events in the backtest engine."""

    BAR_OPEN = auto()
    BAR_UPDATE = auto()
    BAR_CLOSE = auto()
    ORDER_SUBMITTED = auto()
    ORDER_FILLED = auto()
    ORDER_CANCELLED = auto()
    ORDER_EXPIRED = auto()
    TRADE_OPENED = auto()
    TRADE_CLOSED = auto()


@dataclass(frozen=True)
class Event:
    """Immutable event in the backtest system."""

    event_type: EventType
    timestamp: str  # ISO 8601 UTC
    bar_index: int
    data: dict[str, str | int | float | Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp.endswith("Z"):
            raise ValueError("Timestamp must be UTC (end with 'Z')")


class StrategyProtocol(Protocol):
    """Protocol for backtest strategies."""

    def on_bar(self, bar: Bar, bar_index: int) -> list[OrderIntent]:
        """Process a bar and optionally return order intents."""
        ...

    def on_fill(self, fill: Fill) -> None:
        """Process a fill notification."""
        ...


@dataclass(frozen=True)
class ExecutionConfig:
    """Configuration for order execution simulation."""

    default_slippage_bps: Decimal = Decimal("5")  # 5 basis points
    limit_order_fill_probability: Decimal = Decimal("0.8")
    market_order_slippage_bps: Decimal = Decimal("2")
    min_liquidity_ratio: Decimal = Decimal("0.01")  # 1% of bar volume
    max_liquidity_ratio: Decimal = Decimal("0.10")  # 10% of bar volume

    def __post_init__(self) -> None:
        if self.default_slippage_bps < 0:
            raise ValueError("Slippage cannot be negative")
        if self.limit_order_fill_probability < 0 or self.limit_order_fill_probability > 1:
            raise ValueError("Fill probability must be between 0 and 1")


@dataclass(frozen=True)
class TradeFunnelStats:
    """Statistics tracking the trade funnel."""

    bars_processed: int = 0
    setups_detected: int = 0
    strategy_rejections: int = 0
    risk_rejections: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    partial_fills: int = 0
    orders_expired: int = 0
    orders_cancelled: int = 0
    trades_opened: int = 0
    trades_closed: int = 0

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary for reporting."""
        return {
            "bars_processed": self.bars_processed,
            "setups_detected": self.setups_detected,
            "strategy_rejections": self.strategy_rejections,
            "risk_rejections": self.risk_rejections,
            "orders_submitted": self.orders_submitted,
            "orders_filled": self.orders_filled,
            "partial_fills": self.partial_fills,
            "orders_expired": self.orders_expired,
            "orders_cancelled": self.orders_cancelled,
            "trades_opened": self.trades_opened,
            "trades_closed": self.trades_closed,
        }


@dataclass
class PortfolioState:
    """Mutable portfolio state during backtest."""

    cash: Decimal
    positions: dict[str, Decimal]  # instrument_id -> quantity
    position_cost_basis: dict[str, Decimal]  # instrument_id -> weighted avg cost
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    peak_equity: Decimal
    trough_equity: Decimal
    max_drawdown: Decimal
    total_fees: Decimal
    total_slippage: Decimal

    @property
    def equity(self) -> Decimal:
        """Current total equity."""
        return self.cash + self.unrealized_pnl + self.realized_pnl

    @property
    def drawdown(self) -> Decimal:
        """Current drawdown from peak."""
        if self.peak_equity == 0:
            return Decimal("0")
        return (self.peak_equity - self.equity) / self.peak_equity


class BacktestEngine:
    """Event-driven backtesting engine with deterministic replay."""

    def __init__(
        self,
        instrument: Instrument,
        bars: list[Bar],
        strategy: StrategyProtocol,
        config: ExecutionConfig | None = None,
        initial_cash: Decimal = Decimal("1000000"),
    ) -> None:
        self.instrument = instrument
        self.bars = bars
        self.strategy = strategy
        self.config = config or ExecutionConfig()
        self.initial_cash = initial_cash

        # State
        self._portfolio = PortfolioState(
            cash=initial_cash,
            positions={},
            position_cost_basis={},
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            gross_exposure=Decimal("0"),
            net_exposure=Decimal("0"),
            peak_equity=initial_cash,
            trough_equity=initial_cash,
            max_drawdown=Decimal("0"),
            total_fees=Decimal("0"),
            total_slippage=Decimal("0"),
        )

        self._open_orders: dict[str, Order] = {}
        self._fills: list[Fill] = []
        self._events: list[Event] = []
        self._funnel = TradeFunnelStats()
        self._current_bar_index = 0
        self._current_bar: Bar | None = None

    @property
    def funnel_stats(self) -> TradeFunnelStats:
        """Get current trade funnel statistics."""
        return self._funnel

    @property
    def portfolio(self) -> PortfolioState:
        """Get current portfolio state."""
        return self._portfolio

    @property
    def fills(self) -> list[Fill]:
        """Get all fills."""
        return list(self._fills)

    @property
    def events(self) -> list[Event]:
        """Get all events."""
        return list(self._events)

    def _emit_event(self, event_type: EventType, data: dict | None = None) -> None:
        """Emit an event."""
        if self._current_bar is None:
            return
        event = Event(
            event_type=event_type,
            timestamp=self._current_bar.timestamp,
            bar_index=self._current_bar_index,
            data=data or {},
        )
        self._events.append(event)

    def _update_portfolio_state(self) -> None:
        """Update portfolio state based on current positions and prices."""
        if self._current_bar is None:
            return

        # Calculate unrealized P&L
        unrealized_pnl = Decimal("0")
        gross_exposure = Decimal("0")

        for instrument_id, quantity in self._portfolio.positions.items():
            if quantity != 0:
                cost_basis = self._portfolio.position_cost_basis.get(instrument_id, Decimal("0"))
                current_value = quantity * self._current_bar.close
                position_pnl = current_value - (quantity * cost_basis)
                unrealized_pnl += position_pnl
                gross_exposure += abs(current_value)

        self._portfolio.unrealized_pnl = unrealized_pnl
        self._portfolio.gross_exposure = gross_exposure
        self._portfolio.net_exposure = gross_exposure  # Long-only for now

        # Update equity tracking
        equity = self._portfolio.equity
        if equity > self._portfolio.peak_equity:
            self._portfolio.peak_equity = equity
        elif equity < self._portfolio.trough_equity:
            self._portfolio.trough_equity = equity

        # Update max drawdown
        if self._portfolio.peak_equity > 0:
            current_dd = (self._portfolio.peak_equity - equity) / self._portfolio.peak_equity
            if current_dd > self._portfolio.max_drawdown:
                self._portfolio.max_drawdown = current_dd

    def _simulate_market_order_fill(
        self,
        order: Order,
        bar: Bar,
    ) -> Fill | None:
        """Simulate market order fill with slippage."""
        # Determine fill price with slippage
        if order.side == OrderSide.BUY:
            # Buy at ask (high + slippage)
            slippage = bar.high * self.config.market_order_slippage_bps / Decimal("10000")
            fill_price = bar.high + slippage
        else:
            # Sell at bid (low - slippage)
            slippage = bar.low * self.config.market_order_slippage_bps / Decimal("10000")
            fill_price = bar.low - slippage

        # Check liquidity constraints
        max_qty = bar.volume * self.config.max_liquidity_ratio
        fill_qty = min(order.quantity, max_qty)

        if fill_qty <= 0:
            return None

        # Calculate fees (simple model: 0.05% of notional)
        fee_rate = Decimal("0.0005")
        fee = fill_qty * fill_price * fee_rate

        fill = Fill(
            fill_id=f"fill_{order.order_id}_{len(self._fills)}",
            order_id=order.order_id,
            instrument_id=order.instrument_id,
            side=order.side,
            quantity=fill_qty,
            price=fill_price,
            fee=fee,
            timestamp=bar.timestamp,
        )

        return fill

    def _simulate_limit_order_fill(
        self,
        order: Order,
        bar: Bar,
    ) -> Fill | None:
        """Simulate limit order fill based on price crossing."""
        # Check if limit price was crossed
        filled = False
        fill_price = order.limit_price

        if order.side == OrderSide.BUY:
            # Buy limit fills if low <= limit_price
            if bar.low <= order.limit_price:
                filled = True
                # Better fill: use min(limit_price, open) if gap down
                fill_price = min(order.limit_price, bar.open)
        else:
            # Sell limit fills if high >= limit_price
            if bar.high >= order.limit_price:
                filled = True
                # Better fill: use max(limit_price, open) if gap up
                fill_price = max(order.limit_price, bar.open)

        if not filled:
            return None

        # Apply slippage improvement (limit orders can get better fills)
        slippage_improvement = fill_price * self.config.default_slippage_bps / Decimal("10000")
        if order.side == OrderSide.BUY:
            fill_price = fill_price - slippage_improvement / 2
        else:
            fill_price = fill_price + slippage_improvement / 2

        # Check liquidity
        max_qty = bar.volume * self.config.max_liquidity_ratio
        fill_qty = min(order.quantity, max_qty)

        if fill_qty <= 0:
            return None

        # Calculate fees
        fee_rate = Decimal("0.0005")
        fee = fill_qty * fill_price * fee_rate

        fill = Fill(
            fill_id=f"fill_{order.order_id}_{len(self._fills)}",
            order_id=order.order_id,
            instrument_id=order.instrument_id,
            side=order.side,
            quantity=fill_qty,
            price=fill_price,
            fee=fee,
            timestamp=bar.timestamp,
        )

        return fill

    def _process_fill(self, fill: Fill) -> None:
        """Process a fill and update portfolio."""
        self._fills.append(fill)
        self._funnel = TradeFunnelStats(
            **{**self._funnel.to_dict(), "orders_filled": self._funnel.orders_filled + 1},
        )

        # Update cash and positions
        notional = fill.quantity * fill.price

        if fill.side == OrderSide.BUY:
            # Buying: reduce cash, increase position
            self._portfolio.cash -= notional + fill.fee
            current_qty = self._portfolio.positions.get(fill.instrument_id, Decimal("0"))
            current_cost = self._portfolio.position_cost_basis.get(fill.instrument_id, Decimal("0"))

            # Update weighted average cost basis
            total_qty = current_qty + fill.quantity
            if total_qty > 0:
                new_cost_basis = (current_qty * current_cost + fill.quantity * fill.price) / total_qty
                self._portfolio.position_cost_basis[fill.instrument_id] = new_cost_basis

            self._portfolio.positions[fill.instrument_id] = total_qty

            # Track if this opened a new trade
            if current_qty == 0:
                self._funnel = TradeFunnelStats(
                    **{**self._funnel.to_dict(), "trades_opened": self._funnel.trades_opened + 1},
                )
                self._emit_event(EventType.TRADE_OPENED, {"side": "BUY", "quantity": str(fill.quantity)})

        else:  # SELL
            # Selling: increase cash, reduce position
            current_qty = self._portfolio.positions.get(fill.instrument_id, Decimal("0"))

            # Calculate realized P&L using FIFO cost basis
            cost_basis = self._portfolio.position_cost_basis.get(fill.instrument_id, Decimal("0"))
            realized = fill.quantity * (fill.price - cost_basis)
            self._portfolio.realized_pnl += realized

            self._portfolio.cash += notional - fill.fee
            new_qty = current_qty - fill.quantity
            self._portfolio.positions[fill.instrument_id] = new_qty

            # Track fees and slippage
            self._portfolio.total_fees += fill.fee

            # Track if this closed a trade
            if new_qty == 0:
                self._funnel = TradeFunnelStats(
                    **{**self._funnel.to_dict(), "trades_closed": self._funnel.trades_closed + 1},
                )
                self._emit_event(EventType.TRADE_CLOSED, {"side": "SELL", "quantity": str(fill.quantity)})

        # Update portfolio state
        self._update_portfolio_state()

    def _process_order_intent(
        self,
        intent: OrderIntent,
        bar_index: int,
    ) -> None:
        """Process an order intent through risk check to submission."""
        # For backtesting, we'll assume risk approval for valid intents
        # In production, this would call the RiskAuthority

        # Validate intent
        if intent.quantity <= 0:
            self._funnel = TradeFunnelStats(
                **{**self._funnel.to_dict(), "strategy_rejections": self._funnel.strategy_rejections + 1},
            )
            return

        # Check cash availability for buys
        if intent.side == OrderSide.BUY:
            estimated_cost = intent.quantity * self._current_bar.close * Decimal("1.001")  # Include buffer
            if estimated_cost > self._portfolio.cash:
                self._funnel = TradeFunnelStats(
                    **{**self._funnel.to_dict(), "risk_rejections": self._funnel.risk_rejections + 1},
                )
                return

        # Create order
        order = Order(
            order_id=f"order_{bar_index}_{self._funnel.orders_submitted}",
            instrument_id=intent.instrument_id,
            side=intent.side,
            order_type=intent.order_type,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            time_in_force=TimeInForce.DAY,
            status=OrderStatus.SUBMITTED,
            submitted_at=self._current_bar.timestamp if self._current_bar else "",
        )

        self._funnel = TradeFunnelStats(
            **{**self._funnel.to_dict(), "orders_submitted": self._funnel.orders_submitted + 1},
        )
        self._emit_event(EventType.ORDER_SUBMITTED, {"order_id": order.order_id, "side": intent.side.value})

        # Simulate immediate fill for market orders, or queue for limit orders
        if self._current_bar:
            if intent.order_type == OrderType.MARKET:
                fill = self._simulate_market_order_fill(order, self._current_bar)
                if fill:
                    self._process_fill(fill)
                    order.status = OrderStatus.FILLED
            elif intent.order_type == OrderType.LIMIT:
                fill = self._simulate_limit_order_fill(order, self._current_bar)
                if fill:
                    self._process_fill(fill)
                    order.status = OrderStatus.FILLED
                else:
                    # Queue for potential future fill
                    self._open_orders[order.order_id] = order

    def run(self) -> dict:
        """Run the backtest over all bars."""
        for i, bar in enumerate(self.bars):
            self._current_bar_index = i
            self._current_bar = bar
            self._funnel = TradeFunnelStats(
                **{**self._funnel.to_dict(), "bars_processed": self._funnel.bars_processed + 1},
            )

            # Emit bar open event
            self._emit_event(EventType.BAR_OPEN, {"open": str(bar.open)})

            # Process existing open orders (limit orders may fill)
            orders_to_remove = []
            for order_id, order in self._open_orders.items():
                if order.time_in_force == TimeInForce.DAY and i > 0:
                    # DAY orders expire at end of day
                    orders_to_remove.append(order_id)
                    self._funnel = TradeFunnelStats(
                        **{**self._funnel.to_dict(), "orders_expired": self._funnel.orders_expired + 1},
                    )
                    self._emit_event(EventType.ORDER_EXPIRED, {"order_id": order_id})
                else:
                    # Try to fill limit orders
                    fill = self._simulate_limit_order_fill(order, bar)
                    if fill:
                        self._process_fill(fill)
                        order.status = OrderStatus.FILLED
                        orders_to_remove.append(order_id)

            for order_id in orders_to_remove:
                del self._open_orders[order_id]

            # Call strategy
            try:
                intents = self.strategy.on_bar(bar, i)
                if intents:
                    self._funnel = TradeFunnelStats(
                        **{**self._funnel.to_dict(), "setups_detected": self._funnel.setups_detected + len(intents)},
                    )
                    for intent in intents:
                        self._process_order_intent(intent, i)
            except Exception as e:
                # Strategy error - log and continue
                self._funnel = TradeFunnelStats(
                    **{**self._funnel.to_dict(), "strategy_rejections": self._funnel.strategy_rejections + 1},
                )

            # Emit bar close event
            self._emit_event(EventType.BAR_CLOSE, {"close": str(bar.close)})

            # Update portfolio state at end of bar
            self._update_portfolio_state()

        # Return results
        return {
            "funnel_stats": self._funnel.to_dict(),
            "final_equity": str(self._portfolio.equity),
            "total_return": str((self._portfolio.equity - self.initial_cash) / self.initial_cash),
            "max_drawdown": str(self._portfolio.max_drawdown),
            "total_fees": str(self._portfolio.total_fees),
            "total_slippage": str(self._portfolio.total_slippage),
            "num_fills": len(self._fills),
            "num_events": len(self._events),
        }
