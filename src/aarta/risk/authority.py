"""Independent Risk Authority for AARTA.

The RiskAuthority is responsible for:
- Evaluating order intents against risk limits
- Approving or rejecting orders
- Enforcing paper-only mode (rejecting all live intents)
- Tracking position limits and capital allocation
- Maintaining audit trail of decisions

This module is independent from strategy logic.
Strategies propose; RiskAuthority disposes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from aarta.domain.models import (
    OrderIntent,
    OrderSide,
    RejectionReason,
    RiskDecision,
    RiskDecisionResult,
    RiskLimits,
)


@dataclass(frozen=True)
class PositionState:
    """Current position state for an instrument.

    Attributes:
        instrument_id: Instrument identifier.
        quantity: Current held quantity (non-negative, no short selling).
        average_cost: Average cost basis per unit.
        market_value: Current market value (quantity * last_price).
    """

    instrument_id: str
    quantity: int
    average_cost: Decimal
    market_value: Decimal

    def __post_init__(self) -> None:
        """Validate position constraints."""
        if self.quantity < 0:
            raise ValueError("quantity cannot be negative (no short selling)")
        if self.average_cost < 0:
            raise ValueError("average_cost cannot be negative")
        if self.market_value < 0:
            raise ValueError("market_value cannot be negative")


@dataclass
class RiskAuthorityState:
    """Mutable internal state of the risk authority.

    This is the ONLY mutable component in the risk system.
    All external interfaces remain immutable.

    Attributes:
        positions: Current positions by instrument ID.
        daily_turnover: Total turnover for current session.
        submitted_fingerprints: Set of submitted order fingerprints.
        total_capital: Total available capital.
        allocated_capital: Capital currently deployed in positions.
    """

    positions: dict[str, PositionState] = field(default_factory=dict)
    daily_turnover: Decimal = Decimal(0)
    submitted_fingerprints: set[str] = field(default_factory=set)
    total_capital: Decimal = Decimal(0)
    allocated_capital: Decimal = Decimal(0)


class RiskAuthority:
    """Independent risk authority that evaluates order intents.

    The RiskAuthority enforces:
    - Paper-only mode (all live intents rejected)
    - Position limits
    - Capital allocation limits
    - Order value limits
    - Daily turnover limits
    - Duplicate order prevention
    - Instrument allowlist

    This class maintains internal state but exposes only immutable decisions.
    """

    def __init__(
        self,
        limits: RiskLimits,
        total_capital: Decimal,
    ) -> None:
        """Initialize the risk authority.

        Args:
            limits: Risk limits to enforce.
            total_capital: Total capital available for trading.
        """
        if total_capital <= 0:
            raise ValueError("total_capital must be positive")

        self._limits = limits
        self._state = RiskAuthorityState(total_capital=total_capital)

    @property
    def limits(self) -> RiskLimits:
        """Get the current risk limits (immutable)."""
        return self._limits

    @property
    def daily_turnover(self) -> Decimal:
        """Get current daily turnover."""
        return self._state.daily_turnover

    @property
    def total_capital(self) -> Decimal:
        """Get total capital."""
        return self._state.total_capital

    @property
    def allocated_capital(self) -> Decimal:
        """Get currently allocated capital."""
        return self._state.allocated_capital

    @property
    def available_capital(self) -> Decimal:
        """Get available (unallocated) capital."""
        return self._state.total_capital - self._state.allocated_capital

    def get_position(self, instrument_id: str) -> PositionState | None:
        """Get current position for an instrument."""
        return self._state.positions.get(instrument_id)

    def evaluate_intent(
        self,
        intent: OrderIntent,
        current_price: Decimal,
        is_live: bool = False,
    ) -> RiskDecisionResult:
        """Evaluate an order intent against risk limits.

        Args:
            intent: The order intent to evaluate.
            current_price: Current market price for the instrument.
            is_live: Whether this is a live trading intent (always rejected).

        Returns:
            RiskDecisionResult with APPROVED or REJECTED decision.
        """
        # Rule 1: Always reject live trading intents
        if is_live:
            return RiskDecisionResult(
                decision=RiskDecision.REJECTED,
                reason=RejectionReason.LIVE_TRADING_DISABLED,
                details="Live trading is not permitted in this version of AARTA.",
            )

        # Rule 2: Check instrument allowlist
        if (
            self._limits.allowed_instruments
            and intent.instrument_id not in self._limits.allowed_instruments
        ):
            return RiskDecisionResult(
                decision=RiskDecision.REJECTED,
                reason=RejectionReason.INVALID_INSTRUMENT,
                details=f"Instrument {intent.instrument_id} not in allowlist.",
            )

        # Rule 3: Validate order value against max_order_value
        order_value = Decimal(intent.quantity) * current_price
        if order_value > self._limits.max_order_value:
            return RiskDecisionResult(
                decision=RiskDecision.REJECTED,
                reason=RejectionReason.EXCEEDS_CAPITAL_ALLOCATION,
                details=f"Order value {order_value} exceeds max {self._limits.max_order_value}.",
            )

        # Rule 4: Check duplicate order fingerprint
        fingerprint = intent.fingerprint
        if fingerprint in self._state.submitted_fingerprints:
            return RiskDecisionResult(
                decision=RiskDecision.REJECTED,
                reason=RejectionReason.DUPLICATE_ORDER,
                details="Order with same fingerprint already submitted.",
            )

        # Rule 5: Check daily turnover limit
        if self._state.daily_turnover + order_value > self._limits.max_daily_turnover:
            return RiskDecisionResult(
                decision=RiskDecision.REJECTED,
                reason=RejectionReason.EXCEEDS_CAPITAL_ALLOCATION,
                details="Would exceed daily turnover limit.",
            )

        # Rule 6: For BUY orders, check available capital
        if intent.side == OrderSide.BUY:
            required_capital = order_value
            if required_capital > self.available_capital:
                return RiskDecisionResult(
                    decision=RiskDecision.REJECTED,
                    reason=RejectionReason.INSUFFICIENT_CAPITAL,
                    details=f"Required {required_capital}, available {self.available_capital}.",
                )

        # Rule 7: For SELL orders, check position exists
        if intent.side == OrderSide.SELL:
            position = self.get_position(intent.instrument_id)
            if position is None or position.quantity < intent.quantity:
                return RiskDecisionResult(
                    decision=RiskDecision.REJECTED,
                    reason=RejectionReason.INVALID_QUANTITY,
                    details="Cannot sell more than held position (no short selling).",
                )

        # Rule 8: Check max open positions (for new BUY orders)
        if intent.side == OrderSide.BUY:
            current_positions = sum(
                1 for p in self._state.positions.values() if p.quantity > 0
            )
            if current_positions >= self._limits.max_open_positions:
                existing_position = self.get_position(intent.instrument_id)
                if existing_position is None or existing_position.quantity == 0:
                    return RiskDecisionResult(
                        decision=RiskDecision.REJECTED,
                        reason=RejectionReason.EXCEEDS_POSITION_LIMIT,
                        details=f"Maximum {self._limits.max_open_positions} open positions allowed.",
                    )

        # All checks passed
        return RiskDecisionResult(
            decision=RiskDecision.APPROVED,
            reason=None,
            details="Order intent approved by risk authority.",
        )

    def record_submission(self, intent: OrderIntent) -> None:
        """Record that an order has been submitted.

        Must be called after risk approval and before execution.

        Args:
            intent: The submitted order intent.
        """
        self._state.submitted_fingerprints.add(intent.fingerprint)

    def record_fill(
        self,
        instrument_id: str,
        side: OrderSide,
        quantity: int,
        price: Decimal,
        fee: Decimal,
    ) -> None:
        """Record a fill and update position state.

        Args:
            instrument_id: Instrument being traded.
            side: Buy or sell.
            quantity: Filled quantity.
            price: Fill price.
            fee: Transaction fee.
        """
        # Update daily turnover
        trade_value = Decimal(quantity) * price
        self._state.daily_turnover += trade_value

        # Update position
        existing = self._state.positions.get(instrument_id)

        if side == OrderSide.BUY:
            if existing is None or existing.quantity == 0:
                # New position
                total_cost = trade_value + fee
                self._state.positions[instrument_id] = PositionState(
                    instrument_id=instrument_id,
                    quantity=quantity,
                    average_cost=total_cost / Decimal(quantity),
                    market_value=trade_value,
                )
            else:
                # Add to existing position (weighted average)
                total_cost = (
                    Decimal(existing.quantity) * existing.average_cost
                    + trade_value
                    + fee
                )
                new_quantity = existing.quantity + quantity
                self._state.positions[instrument_id] = PositionState(
                    instrument_id=instrument_id,
                    quantity=new_quantity,
                    average_cost=total_cost / Decimal(new_quantity),
                    market_value=trade_value,
                )
            self._state.allocated_capital += trade_value + fee

        elif side == OrderSide.SELL:
            if existing is None:
                raise ValueError("Cannot sell without existing position")

            if existing.quantity < quantity:
                raise ValueError("Cannot sell more than held")

            # Reduce position
            new_quantity = existing.quantity - quantity

            if new_quantity == 0:
                del self._state.positions[instrument_id]
                self._state.allocated_capital -= (
                    Decimal(quantity) * existing.average_cost + fee
                )
            else:
                self._state.positions[instrument_id] = PositionState(
                    instrument_id=instrument_id,
                    quantity=new_quantity,
                    average_cost=existing.average_cost,
                    market_value=Decimal(new_quantity) * price,
                )
                self._state.allocated_capital -= (
                    Decimal(quantity) * existing.average_cost + fee
                )

    def reset_daily_turnover(self) -> None:
        """Reset daily turnover counter (called at session start)."""
        self._state.daily_turnover = Decimal(0)

    def clear_submitted_fingerprints(self) -> None:
        """Clear submitted fingerprints (called at session start)."""
        self._state.submitted_fingerprints.clear()
