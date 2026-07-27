"""Tests for domain models."""

from __future__ import annotations

from decimal import Decimal

import pytest

from aarta.domain.models import (
    Bar,
    Fill,
    Instrument,
    OrderIntent,
    OrderSide,
    OrderType,
    Quote,
    RejectionReason,
    RiskDecision,
    RiskDecisionResult,
    RiskLimits,
    TimeInForce,
)


class TestInstrument:
    """Tests for Instrument model."""

    def test_create_valid_instrument(self) -> None:
        """Test creating a valid instrument."""
        inst = Instrument(
            symbol="NIFTYBEES",
            name="Nippon India ETF Nifty BeES",
            exchange="NSE",
            lot_size=1,
            tick_size=Decimal("0.05"),
            currency="INR",
            instrument_type="ETF",
        )
        assert inst.symbol == "NIFTYBEES"
        assert inst.lot_size == 1
        assert inst.tick_size == Decimal("0.05")

    def test_identity_is_deterministic(self) -> None:
        """Test that identity is deterministic."""
        inst1 = Instrument(
            symbol="NIFTYBEES",
            name="Nippon India ETF Nifty BeES",
            exchange="NSE",
            lot_size=1,
            tick_size=Decimal("0.05"),
            currency="INR",
            instrument_type="ETF",
        )
        inst2 = Instrument(
            symbol="NIFTYBEES",
            name="Nippon India ETF Nifty BeES",
            exchange="NSE",
            lot_size=1,
            tick_size=Decimal("0.05"),
            currency="INR",
            instrument_type="ETF",
        )
        assert inst1.identity == inst2.identity

    def test_rejects_empty_symbol(self) -> None:
        """Test that empty symbol is rejected."""
        with pytest.raises(ValueError, match="symbol cannot be empty"):
            Instrument(
                symbol="",
                name="Test",
                exchange="NSE",
                lot_size=1,
                tick_size=Decimal("0.05"),
                currency="INR",
                instrument_type="ETF",
            )

    def test_rejects_invalid_lot_size(self) -> None:
        """Test that non-positive lot_size is rejected."""
        with pytest.raises(ValueError, match="lot_size must be positive"):
            Instrument(
                symbol="TEST",
                name="Test",
                exchange="NSE",
                lot_size=0,
                tick_size=Decimal("0.05"),
                currency="INR",
                instrument_type="ETF",
            )

    def test_rejects_invalid_tick_size(self) -> None:
        """Test that non-positive tick_size is rejected."""
        with pytest.raises(ValueError, match="tick_size must be positive"):
            Instrument(
                symbol="TEST",
                name="Test",
                exchange="NSE",
                lot_size=1,
                tick_size=Decimal("-0.05"),
                currency="INR",
                instrument_type="ETF",
            )


class TestBar:
    """Tests for Bar model."""

    def test_create_valid_bar(self) -> None:
        """Test creating a valid bar."""
        bar = Bar(
            instrument_id="abc123",
            timestamp="2024-01-15T09:15:00+00:00",
            open=Decimal("22000.00"),
            high=Decimal("22050.00"),
            low=Decimal("21980.00"),
            close=Decimal("22030.00"),
            volume=1000000,
        )
        assert bar.open == Decimal("22000.00")
        assert bar.volume == 1000000

    def test_identity_is_deterministic(self) -> None:
        """Test that bar identity is deterministic."""
        bar1 = Bar(
            instrument_id="abc123",
            timestamp="2024-01-15T09:15:00+00:00",
            open=Decimal("22000.00"),
            high=Decimal("22050.00"),
            low=Decimal("21980.00"),
            close=Decimal("22030.00"),
            volume=1000000,
        )
        bar2 = Bar(
            instrument_id="abc123",
            timestamp="2024-01-15T09:15:00+00:00",
            open=Decimal("22000.00"),
            high=Decimal("22050.00"),
            low=Decimal("21980.00"),
            close=Decimal("22030.00"),
            volume=1000000,
        )
        assert bar1.identity == bar2.identity

    def test_rejects_low_greater_than_high(self) -> None:
        """Test that low > high is rejected."""
        with pytest.raises(ValueError, match="low cannot exceed high"):
            Bar(
                instrument_id="abc123",
                timestamp="2024-01-15T09:15:00+00:00",
                open=Decimal("22000.00"),
                high=Decimal("21900.00"),
                low=Decimal("22100.00"),
                close=Decimal("22030.00"),
                volume=1000000,
            )

    def test_rejects_open_outside_range(self) -> None:
        """Test that open outside [low, high] is rejected."""
        with pytest.raises(ValueError, match="open must be within"):
            Bar(
                instrument_id="abc123",
                timestamp="2024-01-15T09:15:00+00:00",
                open=Decimal("22100.00"),
                high=Decimal("22050.00"),
                low=Decimal("21980.00"),
                close=Decimal("22030.00"),
                volume=1000000,
            )

    def test_rejects_negative_volume(self) -> None:
        """Test that negative volume is rejected."""
        with pytest.raises(ValueError, match="volume cannot be negative"):
            Bar(
                instrument_id="abc123",
                timestamp="2024-01-15T09:15:00+00:00",
                open=Decimal("22000.00"),
                high=Decimal("22050.00"),
                low=Decimal("21980.00"),
                close=Decimal("22030.00"),
                volume=-100,
            )


class TestQuote:
    """Tests for Quote model."""

    def test_create_valid_quote(self) -> None:
        """Test creating a valid quote."""
        quote = Quote(
            instrument_id="abc123",
            timestamp="2024-01-15T09:15:00+00:00",
            bid_price=Decimal("22000.00"),
            ask_price=Decimal("22000.50"),
            bid_size=100,
            ask_size=150,
        )
        assert quote.bid_price < quote.ask_price

    def test_rejects_bid_geq_ask(self) -> None:
        """Test that bid >= ask is rejected."""
        with pytest.raises(ValueError, match="bid_price must be less than ask_price"):
            Quote(
                instrument_id="abc123",
                timestamp="2024-01-15T09:15:00+00:00",
                bid_price=Decimal("22000.50"),
                ask_price=Decimal("22000.00"),
                bid_size=100,
                ask_size=150,
            )


class TestOrderIntent:
    """Tests for OrderIntent model."""

    def test_create_market_buy_intent(self) -> None:
        """Test creating a market buy intent."""
        intent = OrderIntent(
            strategy_id="strategy_001",
            instrument_id="abc123",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            limit_price=None,
            time_in_force=TimeInForce.DAY,
            client_order_id="client_001",
            timestamp="2024-01-15T09:15:00+00:00",
        )
        assert intent.side == OrderSide.BUY
        assert intent.order_type == OrderType.MARKET
        assert intent.limit_price is None

    def test_create_limit_buy_intent(self) -> None:
        """Test creating a limit buy intent."""
        intent = OrderIntent(
            strategy_id="strategy_001",
            instrument_id="abc123",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            limit_price=Decimal("22000.00"),
            time_in_force=TimeInForce.DAY,
            client_order_id="client_001",
            timestamp="2024-01-15T09:15:00+00:00",
        )
        assert intent.limit_price == Decimal("22000.00")

    def test_fingerprint_is_deterministic(self) -> None:
        """Test that fingerprint is deterministic."""
        intent1 = OrderIntent(
            strategy_id="strategy_001",
            instrument_id="abc123",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            limit_price=None,
            time_in_force=TimeInForce.DAY,
            client_order_id="client_001",
            timestamp="2024-01-15T09:15:00+00:00",
        )
        intent2 = OrderIntent(
            strategy_id="strategy_001",
            instrument_id="abc123",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            limit_price=None,
            time_in_force=TimeInForce.DAY,
            client_order_id="client_001",
            timestamp="2024-01-15T09:15:00+00:00",
        )
        assert intent1.fingerprint == intent2.fingerprint

    def test_rejects_limit_order_without_price(self) -> None:
        """Test that LIMIT order without price is rejected."""
        with pytest.raises(ValueError, match="limit_price required"):
            OrderIntent(
                strategy_id="strategy_001",
                instrument_id="abc123",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=10,
                limit_price=None,
                time_in_force=TimeInForce.DAY,
                client_order_id="client_001",
                timestamp="2024-01-15T09:15:00+00:00",
            )

    def test_rejects_market_order_with_price(self) -> None:
        """Test that MARKET order with price is rejected."""
        with pytest.raises(ValueError, match="limit_price not allowed"):
            OrderIntent(
                strategy_id="strategy_001",
                instrument_id="abc123",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=10,
                limit_price=Decimal("22000.00"),
                time_in_force=TimeInForce.DAY,
                client_order_id="client_001",
                timestamp="2024-01-15T09:15:00+00:00",
            )

    def test_rejects_zero_quantity(self) -> None:
        """Test that zero quantity is rejected."""
        with pytest.raises(ValueError, match="quantity must be positive"):
            OrderIntent(
                strategy_id="strategy_001",
                instrument_id="abc123",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=0,
                limit_price=None,
                time_in_force=TimeInForce.DAY,
                client_order_id="client_001",
                timestamp="2024-01-15T09:15:00+00:00",
            )


class TestFill:
    """Tests for Fill model."""

    def test_create_valid_fill(self) -> None:
        """Test creating a valid fill."""
        fill = Fill(
            fill_id="fill_001",
            order_id="order_001",
            instrument_id="abc123",
            side=OrderSide.BUY,
            quantity=10,
            price=Decimal("22000.00"),
            fee=Decimal("10.00"),
            timestamp="2024-01-15T09:15:00+00:00",
        )
        assert fill.quantity == 10
        assert fill.net_amount == Decimal("220010.00")

    def test_net_amount_calculation(self) -> None:
        """Test net amount calculation."""
        fill = Fill(
            fill_id="fill_001",
            order_id="order_001",
            instrument_id="abc123",
            side=OrderSide.BUY,
            quantity=10,
            price=Decimal("22000.00"),
            fee=Decimal("10.00"),
            timestamp="2024-01-15T09:15:00+00:00",
        )
        expected = Decimal(10) * Decimal("22000.00") + Decimal("10.00")
        assert fill.net_amount == expected

    def test_rejects_negative_fee(self) -> None:
        """Test that negative fee is rejected."""
        with pytest.raises(ValueError, match="fee cannot be negative"):
            Fill(
                fill_id="fill_001",
                order_id="order_001",
                instrument_id="abc123",
                side=OrderSide.BUY,
                quantity=10,
                price=Decimal("22000.00"),
                fee=Decimal("-10.00"),
                timestamp="2024-01-15T09:15:00+00:00",
            )


class TestRiskLimits:
    """Tests for RiskLimits model."""

    def test_create_valid_limits(self) -> None:
        """Test creating valid risk limits."""
        limits = RiskLimits(
            max_position_value=Decimal("100000.00"),
            max_order_value=Decimal("50000.00"),
            max_daily_turnover=Decimal("500000.00"),
            max_open_positions=5,
        )
        assert limits.max_open_positions == 5

    def test_create_limits_with_allowlist(self) -> None:
        """Test creating limits with instrument allowlist."""
        limits = RiskLimits(
            max_position_value=Decimal("100000.00"),
            max_order_value=Decimal("50000.00"),
            max_daily_turnover=Decimal("500000.00"),
            max_open_positions=5,
            allowed_instruments=frozenset(["inst_001", "inst_002"]),
        )
        assert "inst_001" in limits.allowed_instruments

    def test_rejects_invalid_max_position_value(self) -> None:
        """Test that non-positive max_position_value is rejected."""
        with pytest.raises(ValueError, match="max_position_value must be positive"):
            RiskLimits(
                max_position_value=Decimal(0),
                max_order_value=Decimal("50000.00"),
                max_daily_turnover=Decimal("500000.00"),
                max_open_positions=5,
            )


class TestRiskDecisionResult:
    """Tests for RiskDecisionResult model."""

    def test_create_approved_decision(self) -> None:
        """Test creating an approved decision."""
        result = RiskDecisionResult(
            decision=RiskDecision.APPROVED,
            reason=None,
            details="Order approved.",
        )
        assert result.decision == RiskDecision.APPROVED
        assert result.reason is None

    def test_create_rejected_decision(self) -> None:
        """Test creating a rejected decision."""
        result = RiskDecisionResult(
            decision=RiskDecision.REJECTED,
            reason=RejectionReason.LIVE_TRADING_DISABLED,
            details="Live trading disabled.",
        )
        assert result.decision == RiskDecision.REJECTED
        assert result.reason == RejectionReason.LIVE_TRADING_DISABLED

    def test_rejects_approved_with_reason(self) -> None:
        """Test that APPROVED with reason is rejected."""
        with pytest.raises(ValueError, match="reason must be None"):
            RiskDecisionResult(
                decision=RiskDecision.APPROVED,
                reason=RejectionReason.UNKNOWN,
                details="Test.",
            )

    def test_rejects_rejected_without_reason(self) -> None:
        """Test that REJECTED without reason is rejected."""
        with pytest.raises(ValueError, match="reason required"):
            RiskDecisionResult(
                decision=RiskDecision.REJECTED,
                reason=None,
                details="Test.",
            )
