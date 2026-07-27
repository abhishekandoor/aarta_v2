"""Tests for the backtest engine."""

from decimal import Decimal

import pytest

from aarta.backtest.engine import (
    BacktestEngine,
    Event,
    EventType,
    ExecutionConfig,
    TradeFunnelStats,
)
from aarta.domain.models import (
    Bar,
    Instrument,
    OrderIntent,
    OrderSide,
    OrderType,
)


class DummyStrategy:
    """A simple strategy for testing."""

    def __init__(self, buy_at_index: int | None = None, sell_at_index: int | None = None) -> None:
        self.buy_at_index = buy_at_index
        self.sell_at_index = sell_at_index
        self.fills_received: list = []
        self.position = Decimal("0")

    def on_bar(self, bar: Bar, bar_index: int) -> list[OrderIntent]:
        """Generate order intents based on bar index."""
        intents = []

        if self.buy_at_index is not None and bar_index == self.buy_at_index:
            # Buy intent
            intents.append(
                OrderIntent(
                    strategy_id="dummy",
                    instrument_id="TEST",
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=10,
                    limit_price=None,
                    time_in_force=TimeInForce.DAY,
                    client_order_id=f"buy_{bar_index}",
                    timestamp=bar.timestamp,
                )
            )

        if self.sell_at_index is not None and bar_index == self.sell_at_index:
            # Sell intent
            intents.append(
                OrderIntent(
                    strategy_id="dummy",
                    instrument_id="TEST",
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=10,
                    limit_price=None,
                    time_in_force=TimeInForce.DAY,
                    client_order_id=f"sell_{bar_index}",
                    timestamp=bar.timestamp,
                )
            )

        return intents

    def on_fill(self, fill) -> None:
        """Track fills."""
        self.fills_received.append(fill)
        if fill.side == OrderSide.BUY:
            self.position += fill.quantity
        else:
            self.position -= fill.quantity


def _create_test_instrument() -> Instrument:
    """Create a test instrument."""
    return Instrument(
        symbol="TESTETF",
        name="Test ETF",
        exchange="NSE",
        lot_size=1,
        tick_size=Decimal("0.05"),
        currency="INR",
        instrument_type="ETF",
    )


def _create_test_bars() -> list[Bar]:
    """Create a series of test bars."""
    bars = []

    for i in range(10):
        # Create bars with increasing prices
        open_price = Decimal("100") + Decimal(i)
        high_price = open_price + Decimal("2")
        low_price = open_price - Decimal("1")
        close_price = open_price + Decimal("1")

        bar = Bar(
            instrument_id="TEST",
            timestamp=f"2024-01-01T{9 + i // 4}:{15 + (i % 4) * 15}:00Z",
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=1000,
        )
        bars.append(bar)

    return bars


class TestEvent:
    """Tests for the Event class."""

    def test_valid_event_creation(self) -> None:
        """Test creating a valid event."""
        event = Event(
            event_type=EventType.BAR_OPEN,
            timestamp="2024-01-01T09:15:00Z",
            bar_index=0,
            data={"open": "100"},
        )
        assert event.event_type == EventType.BAR_OPEN
        assert event.bar_index == 0
        assert event.data["open"] == "100"

    def test_event_requires_utc_timestamp(self) -> None:
        """Test that events require UTC timestamps."""
        with pytest.raises(ValueError, match="UTC"):
            Event(
                event_type=EventType.BAR_OPEN,
                timestamp="2024-01-01T09:15:00",  # Missing 'Z'
                bar_index=0,
            )

    def test_event_immutability(self) -> None:
        """Test that events are immutable."""
        event = Event(
            event_type=EventType.BAR_OPEN,
            timestamp="2024-01-01T09:15:00Z",
            bar_index=0,
        )
        with pytest.raises(Exception):  # frozen dataclass raises various errors
            event.bar_index = 1  # type: ignore[misc]


class TestExecutionConfig:
    """Tests for ExecutionConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = ExecutionConfig()
        assert config.default_slippage_bps == Decimal("5")
        assert config.market_order_slippage_bps == Decimal("2")
        assert config.max_liquidity_ratio == Decimal("0.10")

    def test_negative_slippage_rejected(self) -> None:
        """Test that negative slippage is rejected."""
        with pytest.raises(ValueError, match="negative"):
            ExecutionConfig(default_slippage_bps=Decimal("-1"))

    def test_invalid_fill_probability_rejected(self) -> None:
        """Test that invalid fill probability is rejected."""
        with pytest.raises(ValueError, match="probability"):
            ExecutionConfig(limit_order_fill_probability=Decimal("1.5"))


class TestTradeFunnelStats:
    """Tests for TradeFunnelStats."""

    def test_initial_state(self) -> None:
        """Test initial funnel state."""
        stats = TradeFunnelStats()
        assert stats.bars_processed == 0
        assert stats.orders_filled == 0
        assert stats.trades_opened == 0

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        stats = TradeFunnelStats(bars_processed=5, orders_filled=3)
        d = stats.to_dict()
        assert d["bars_processed"] == 5
        assert d["orders_filled"] == 3


class TestBacktestEngine:
    """Tests for the BacktestEngine."""

    def test_engine_initialization(self) -> None:
        """Test engine initialization."""
        instrument = _create_test_instrument()
        bars = _create_test_bars()
        strategy = DummyStrategy()

        engine = BacktestEngine(
            instrument=instrument,
            bars=bars,
            strategy=strategy,
            initial_cash=Decimal("1000000"),
        )

        assert engine.initial_cash == Decimal("1000000")
        assert engine.portfolio.cash == Decimal("1000000")
        assert len(engine.bars) == 10

    def test_run_no_trades(self) -> None:
        """Test running backtest with no trades."""
        instrument = _create_test_instrument()
        bars = _create_test_bars()
        strategy = DummyStrategy()  # No buy/sell signals

        engine = BacktestEngine(
            instrument=instrument,
            bars=bars,
            strategy=strategy,
        )

        results = engine.run()

        assert results["funnel_stats"]["bars_processed"] == 10
        assert results["funnel_stats"]["trades_opened"] == 0
        assert results["funnel_stats"]["trades_closed"] == 0
        assert results["final_equity"] == str(Decimal("1000000"))

    def test_run_with_buy_signal(self) -> None:
        """Test running backtest with a buy signal."""
        instrument = _create_test_instrument()
        bars = _create_test_bars()
        strategy = DummyStrategy(buy_at_index=0)

        engine = BacktestEngine(
            instrument=instrument,
            bars=bars,
            strategy=strategy,
            initial_cash=Decimal("1000000"),
        )

        results = engine.run()

        assert results["funnel_stats"]["bars_processed"] == 10
        assert results["funnel_stats"]["trades_opened"] >= 1
        assert results["funnel_stats"]["orders_filled"] >= 1
        assert results["num_fills"] >= 1

    def test_run_with_buy_and_sell(self) -> None:
        """Test running backtest with buy and sell signals."""
        instrument = _create_test_instrument()
        bars = _create_test_bars()
        strategy = DummyStrategy(buy_at_index=0, sell_at_index=5)

        engine = BacktestEngine(
            instrument=instrument,
            bars=bars,
            strategy=strategy,
            initial_cash=Decimal("1000000"),
        )

        results = engine.run()

        assert results["funnel_stats"]["trades_opened"] >= 1
        assert results["funnel_stats"]["trades_closed"] >= 1

    def test_funnel_tracking(self) -> None:
        """Test that funnel statistics are tracked correctly."""
        instrument = _create_test_instrument()
        bars = _create_test_bars()
        strategy = DummyStrategy(buy_at_index=0)

        engine = BacktestEngine(
            instrument=instrument,
            bars=bars,
            strategy=strategy,
        )

        engine.run()

        funnel = engine.funnel_stats
        assert funnel.bars_processed == 10
        assert funnel.setups_detected >= 1
        assert funnel.orders_submitted >= 1

    def test_portfolio_state_updates(self) -> None:
        """Test that portfolio state updates during backtest."""
        instrument = _create_test_instrument()
        bars = _create_test_bars()
        strategy = DummyStrategy(buy_at_index=0)

        engine = BacktestEngine(
            instrument=instrument,
            bars=bars,
            strategy=strategy,
            initial_cash=Decimal("1000000"),
        )

        engine.run()

        # After buying, cash should decrease and position should exist
        assert engine.portfolio.cash < Decimal("1000000")
        assert "TEST" in engine.portfolio.positions
        assert engine.portfolio.positions["TEST"] > 0

    def test_events_emitted(self) -> None:
        """Test that events are emitted during backtest."""
        instrument = _create_test_instrument()
        bars = _create_test_bars()
        strategy = DummyStrategy(buy_at_index=0)

        engine = BacktestEngine(
            instrument=instrument,
            bars=bars,
            strategy=strategy,
        )

        engine.run()

        events = engine.events
        assert len(events) > 0

        # Should have BAR_OPEN and BAR_CLOSE events for each bar
        bar_open_events = [e for e in events if e.event_type == EventType.BAR_OPEN]
        bar_close_events = [e for e in events if e.event_type == EventType.BAR_CLOSE]
        assert len(bar_open_events) == 10
        assert len(bar_close_events) == 10

    def test_deterministic_results(self) -> None:
        """Test that results are deterministic."""
        instrument = _create_test_instrument()
        bars = _create_test_bars()
        strategy = DummyStrategy(buy_at_index=0)

        # Run twice
        engine1 = BacktestEngine(
            instrument=instrument,
            bars=bars,
            strategy=strategy,
        )
        results1 = engine1.run()

        engine2 = BacktestEngine(
            instrument=instrument,
            bars=bars,
            strategy=strategy,
        )
        results2 = engine2.run()

        # Results should be identical
        assert results1["final_equity"] == results2["final_equity"]
        assert results1["max_drawdown"] == results2["max_drawdown"]
        assert results1["num_fills"] == results2["num_fills"]

    def test_cash_constraint_rejects_orders(self) -> None:
        """Test that orders are rejected when insufficient cash."""
        instrument = _create_test_instrument()
        bars = _create_test_bars()
        strategy = DummyStrategy(buy_at_index=0)

        # Very small initial cash
        engine = BacktestEngine(
            instrument=instrument,
            bars=bars,
            strategy=strategy,
            initial_cash=Decimal("100"),  # Not enough to buy 10 shares at ~100
        )

        results = engine.run()

        # Order should be rejected due to insufficient cash
        assert results["funnel_stats"]["risk_rejections"] >= 1
        assert results["funnel_stats"]["orders_filled"] == 0

    def test_invalid_quantity_rejected(self) -> None:
        """Test that invalid quantity orders are rejected."""
        instrument = _create_test_instrument()
        bars = _create_test_bars()

        class InvalidStrategy:
            def on_bar(self, bar: Bar, bar_index: int) -> list[OrderIntent]:
                if bar_index == 0:
                    return [
                        OrderIntent(
                            instrument_id="TEST",
                            side=OrderSide.BUY,
                            order_type=OrderType.MARKET,
                            quantity=Decimal("0"),  # Invalid
                            limit_price=None,
                        )
                    ]
                return []

            def on_fill(self, fill) -> None:
                pass

        engine = BacktestEngine(
            instrument=instrument,
            bars=bars,
            strategy=InvalidStrategy(),  # type: ignore[arg-type]
        )

        results = engine.run()

        assert results["funnel_stats"]["strategy_rejections"] >= 1
