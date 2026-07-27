"""Tests for the independent Risk Authority."""

from __future__ import annotations

from decimal import Decimal

import pytest

from aarta.domain.models import (
    OrderIntent,
    OrderSide,
    OrderType,
    RejectionReason,
    RiskDecision,
    RiskLimits,
    TimeInForce,
)
from aarta.risk.authority import PositionState, RiskAuthority


def create_test_intent(
    strategy_id: str = "strategy_001",
    instrument_id: str = "inst_001",
    side: OrderSide = OrderSide.BUY,
    quantity: int = 10,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
    client_order_id: str = "client_001",
) -> OrderIntent:
    """Helper to create test order intents."""
    return OrderIntent(
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id,
        timestamp="2024-01-15T09:15:00+00:00",
    )


def create_test_authority(
    total_capital: Decimal = Decimal("1000000.00"),
    max_order_value: Decimal = Decimal("500000.00"),
    max_open_positions: int = 5,
    allowed_instruments: frozenset[str] | None = None,
) -> RiskAuthority:
    """Helper to create test risk authority."""
    limits = RiskLimits(
        max_position_value=total_capital,
        max_order_value=max_order_value,
        max_daily_turnover=Decimal("5000000.00"),
        max_open_positions=max_open_positions,
        allowed_instruments=allowed_instruments or frozenset(),
    )
    return RiskAuthority(limits=limits, total_capital=total_capital)


class TestRiskAuthorityInitialization:
    """Tests for RiskAuthority initialization."""

    def test_create_valid_authority(self) -> None:
        """Test creating a valid risk authority."""
        authority = create_test_authority()
        assert authority.total_capital == Decimal("1000000.00")
        assert authority.available_capital == Decimal("1000000.00")
        assert authority.daily_turnover == Decimal(0)

    def test_rejects_zero_capital(self) -> None:
        """Test that zero capital is rejected."""
        limits = RiskLimits(
            max_position_value=Decimal("100000.00"),
            max_order_value=Decimal("50000.00"),
            max_daily_turnover=Decimal("500000.00"),
            max_open_positions=5,
        )
        with pytest.raises(ValueError, match="total_capital must be positive"):
            RiskAuthority(limits=limits, total_capital=Decimal(0))


class TestLiveTradingRejection:
    """Tests for live trading rejection - the core safety feature."""

    def test_always_rejects_live_intent(self) -> None:
        """Test that live trading intents are always rejected."""
        authority = create_test_authority()
        intent = create_test_intent()
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=True)

        assert result.decision == RiskDecision.REJECTED
        assert result.reason == RejectionReason.LIVE_TRADING_DISABLED
        assert "Live trading is not permitted" in result.details

    def test_approves_paper_intent(self) -> None:
        """Test that paper trading intents can be approved."""
        authority = create_test_authority()
        intent = create_test_intent()
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.APPROVED
        assert result.reason is None


class TestInstrumentAllowlist:
    """Tests for instrument allowlist enforcement."""

    def test_rejects_non_allowed_instrument(self) -> None:
        """Test that non-allowed instruments are rejected."""
        authority = create_test_authority(
            allowed_instruments=frozenset(["allowed_inst"])
        )
        intent = create_test_intent(instrument_id="not_allowed")
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.REJECTED
        assert result.reason == RejectionReason.INVALID_INSTRUMENT

    def test_approves_allowed_instrument(self) -> None:
        """Test that allowed instruments pass this check."""
        authority = create_test_authority(
            allowed_instruments=frozenset(["allowed_inst"])
        )
        intent = create_test_intent(instrument_id="allowed_inst")
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.APPROVED

    def test_empty_allowlist_means_all_allowed(self) -> None:
        """Test that empty allowlist means all instruments allowed."""
        authority = create_test_authority(allowed_instruments=frozenset())
        intent = create_test_intent(instrument_id="any_instrument")
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.APPROVED


class TestOrderValueLimit:
    """Tests for order value limit enforcement."""

    def test_rejects_excessive_order_value(self) -> None:
        """Test that orders exceeding max_order_value are rejected."""
        authority = create_test_authority(max_order_value=Decimal("10000.00"))
        intent = create_test_intent(quantity=100)  # 100 * 22000 = 2,200,000
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.REJECTED
        assert result.reason == RejectionReason.EXCEEDS_CAPITAL_ALLOCATION

    def test_approves_within_order_value_limit(self) -> None:
        """Test that orders within limit pass this check."""
        authority = create_test_authority(max_order_value=Decimal("500000.00"))
        intent = create_test_intent(quantity=10)  # 10 * 22000 = 220,000
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.APPROVED


class TestDuplicateOrderPrevention:
    """Tests for duplicate order fingerprint detection."""

    def test_rejects_duplicate_fingerprint(self) -> None:
        """Test that duplicate order fingerprints are rejected."""
        authority = create_test_authority()
        intent = create_test_intent(client_order_id="same_id")
        current_price = Decimal("22000.00")

        # First submission should be approved
        result1 = authority.evaluate_intent(intent, current_price, is_live=False)
        assert result1.decision == RiskDecision.APPROVED

        # Record the submission
        authority.record_submission(intent)

        # Second identical intent should be rejected
        result2 = authority.evaluate_intent(intent, current_price, is_live=False)
        assert result2.decision == RiskDecision.REJECTED
        assert result2.reason == RejectionReason.DUPLICATE_ORDER

    def test_different_fingerprints_not_duplicates(self) -> None:
        """Test that different fingerprints are not considered duplicates."""
        authority = create_test_authority()
        intent1 = create_test_intent(client_order_id="id_001")
        intent2 = create_test_intent(client_order_id="id_002")
        current_price = Decimal("22000.00")

        result1 = authority.evaluate_intent(intent1, current_price, is_live=False)
        assert result1.decision == RiskDecision.APPROVED

        authority.record_submission(intent1)

        # Different fingerprint should still be approved
        result2 = authority.evaluate_intent(intent2, current_price, is_live=False)
        assert result2.decision == RiskDecision.APPROVED


class TestDailyTurnoverLimit:
    """Tests for daily turnover limit enforcement."""

    def test_rejects_exceeding_daily_turnover(self) -> None:
        """Test that orders exceeding daily turnover limit are rejected."""
        authority = create_test_authority()
        # Manually set high turnover (close to the 5,000,000 limit)
        authority._state.daily_turnover = Decimal("4900000.00")

        intent = create_test_intent(quantity=100)  # 2,200,000 value
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.REJECTED
        assert result.reason == RejectionReason.EXCEEDS_CAPITAL_ALLOCATION


class TestCapitalChecks:
    """Tests for capital allocation checks."""

    def test_rejects_insufficient_capital_for_buy(self) -> None:
        """Test that BUY orders requiring more than available capital are rejected."""
        authority = create_test_authority(total_capital=Decimal("100000.00"))
        # Allocate most capital
        authority._state.allocated_capital = Decimal("90000.00")

        intent = create_test_intent(quantity=10)  # Needs 220,000
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.REJECTED
        assert result.reason == RejectionReason.INSUFFICIENT_CAPITAL

    def test_approves_buy_with_sufficient_capital(self) -> None:
        """Test that BUY orders with sufficient capital are approved."""
        authority = create_test_authority(total_capital=Decimal("500000.00"))
        intent = create_test_intent(quantity=10)  # Needs 220,000
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.APPROVED


class TestSellOrderValidation:
    """Tests for sell order validation."""

    def test_rejects_sell_without_position(self) -> None:
        """Test that SELL orders without position are rejected."""
        authority = create_test_authority()
        intent = create_test_intent(side=OrderSide.SELL)
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.REJECTED
        assert result.reason == RejectionReason.INVALID_QUANTITY

    def test_rejects_sell_more_than_held(self) -> None:
        """Test that selling more than held quantity is rejected."""
        authority = create_test_authority()
        # Add a position of 10 units
        authority._state.positions["inst_001"] = PositionState(
            instrument_id="inst_001",
            quantity=10,
            average_cost=Decimal("22000.00"),
            market_value=Decimal("220000.00"),
        )

        intent = create_test_intent(side=OrderSide.SELL, quantity=15)
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.REJECTED
        assert result.reason == RejectionReason.INVALID_QUANTITY

    def test_approves_sell_within_position(self) -> None:
        """Test that selling within held quantity is approved."""
        authority = create_test_authority()
        authority._state.positions["inst_001"] = PositionState(
            instrument_id="inst_001",
            quantity=10,
            average_cost=Decimal("22000.00"),
            market_value=Decimal("220000.00"),
        )

        intent = create_test_intent(side=OrderSide.SELL, quantity=5)
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.APPROVED


class TestPositionLimits:
    """Tests for maximum open positions limit."""

    def test_rejects_new_position_at_limit(self) -> None:
        """Test that new positions are rejected when at max Open positions."""
        authority = create_test_authority(max_open_positions=2)
        # Add 2 existing positions
        authority._state.positions["inst_001"] = PositionState(
            instrument_id="inst_001",
            quantity=10,
            average_cost=Decimal("22000.00"),
            market_value=Decimal("220000.00"),
        )
        authority._state.positions["inst_002"] = PositionState(
            instrument_id="inst_002",
            quantity=5,
            average_cost=Decimal("11000.00"),
            market_value=Decimal("55000.00"),
        )

        intent = create_test_intent(instrument_id="inst_003")
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.REJECTED
        assert result.reason == RejectionReason.EXCEEDS_POSITION_LIMIT

    def test_approves_adding_to_existing_position(self) -> None:
        """Test that adding to existing position is allowed even at limit."""
        authority = create_test_authority(max_open_positions=2)
        authority._state.positions["inst_001"] = PositionState(
            instrument_id="inst_001",
            quantity=10,
            average_cost=Decimal("22000.00"),
            market_value=Decimal("220000.00"),
        )
        authority._state.positions["inst_002"] = PositionState(
            instrument_id="inst_002",
            quantity=5,
            average_cost=Decimal("11000.00"),
            market_value=Decimal("55000.00"),
        )

        # Adding to existing position should be allowed
        intent = create_test_intent(instrument_id="inst_001")
        current_price = Decimal("22000.00")

        result = authority.evaluate_intent(intent, current_price, is_live=False)

        assert result.decision == RiskDecision.APPROVED


class TestFillRecording:
    """Tests for fill recording and position updates."""

    def test_record_buy_fill_creates_position(self) -> None:
        """Test that recording a BUY fill creates a new position."""
        authority = create_test_authority()

        authority.record_fill(
            instrument_id="inst_001",
            side=OrderSide.BUY,
            quantity=10,
            price=Decimal("22000.00"),
            fee=Decimal("10.00"),
        )

        position = authority.get_position("inst_001")
        assert position is not None
        assert position.quantity == 10
        assert position.average_cost == Decimal("22001.00")  # (220000 + 10) / 10

    def test_record_sell_fill_reduces_position(self) -> None:
        """Test that recording a SELL fill reduces position."""
        authority = create_test_authority()
        # Create initial position
        authority.record_fill(
            instrument_id="inst_001",
            side=OrderSide.BUY,
            quantity=10,
            price=Decimal("22000.00"),
            fee=Decimal("10.00"),
        )

        # Sell half
        authority.record_fill(
            instrument_id="inst_001",
            side=OrderSide.SELL,
            quantity=5,
            price=Decimal("22100.00"),
            fee=Decimal("5.00"),
        )

        position = authority.get_position("inst_001")
        assert position is not None
        assert position.quantity == 5

    def test_record_fill_updates_daily_turnover(self) -> None:
        """Test that recording fills updates daily turnover."""
        authority = create_test_authority()

        authority.record_fill(
            instrument_id="inst_001",
            side=OrderSide.BUY,
            quantity=10,
            price=Decimal("22000.00"),
            fee=Decimal("10.00"),
        )

        assert authority.daily_turnover == Decimal("220000.00")

    def test_reset_daily_turnover(self) -> None:
        """Test resetting daily turnover."""
        authority = create_test_authority()
        authority._state.daily_turnover = Decimal("100000.00")

        authority.reset_daily_turnover()

        assert authority.daily_turnover == Decimal(0)

    def test_clear_submitted_fingerprints(self) -> None:
        """Test clearing submitted fingerprints."""
        authority = create_test_authority()
        intent = create_test_intent()
        authority.record_submission(intent)

        authority.clear_submitted_fingerprints()

        # Should now approve what was previously a duplicate
        result = authority.evaluate_intent(intent, Decimal("22000.00"), is_live=False)
        assert result.decision == RiskDecision.APPROVED


class TestPositionStateValidation:
    """Tests for PositionState validation."""

    def test_rejects_negative_quantity(self) -> None:
        """Test that negative quantity is rejected."""
        with pytest.raises(ValueError, match="quantity cannot be negative"):
            PositionState(
                instrument_id="inst_001",
                quantity=-10,
                average_cost=Decimal("22000.00"),
                market_value=Decimal("220000.00"),
            )

    def test_rejects_negative_average_cost(self) -> None:
        """Test that negative average_cost is rejected."""
        with pytest.raises(ValueError, match="average_cost cannot be negative"):
            PositionState(
                instrument_id="inst_001",
                quantity=10,
                average_cost=Decimal("-22000.00"),
                market_value=Decimal("220000.00"),
            )
