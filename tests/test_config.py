"""Tests for configuration settings."""

from __future__ import annotations

import dataclasses

import pytest

from aarta.config import DEFAULT_CONFIG, SystemConfig, TradingMode


class TestTradingMode:
    """Tests for TradingMode enum."""

    def test_trading_mode_values(self) -> None:
        """Test that TradingMode has expected values."""
        assert TradingMode.PAPER.value == "paper"
        assert TradingMode.LIVE.value == "live"

    def test_trading_mode_count(self) -> None:
        """Test that exactly two trading modes exist."""
        assert len(list(TradingMode)) == 2


class TestSystemConfig:
    """Tests for SystemConfig dataclass."""

    def test_default_config_is_paper_mode(self) -> None:
        """Test that default configuration uses paper mode."""
        assert DEFAULT_CONFIG.trading_mode == TradingMode.PAPER

    def test_default_config_live_disabled(self) -> None:
        """Test that live trading is disabled by default."""
        assert DEFAULT_CONFIG.live_trading_enabled is False

    def test_default_config_version(self) -> None:
        """Test that default config has version string."""
        assert isinstance(DEFAULT_CONFIG.version, str)
        assert len(DEFAULT_CONFIG.version) > 0

    def test_config_is_immutable(self) -> None:
        """Test that SystemConfig instances are frozen."""
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            DEFAULT_CONFIG.trading_mode = TradingMode.LIVE  # type: ignore[misc]

    def test_config_rejects_live_enabled(self) -> None:
        """Test that SystemConfig rejects live_trading_enabled=True."""
        with pytest.raises(RuntimeError, match="Live trading is not permitted"):
            SystemConfig(
                trading_mode=TradingMode.PAPER,
                live_trading_enabled=True,
                version="test",
            )

    def test_config_rejects_live_mode(self) -> None:
        """Test that SystemConfig rejects LIVE trading mode."""
        with pytest.raises(RuntimeError, match="Live trading mode is not permitted"):
            SystemConfig(
                trading_mode=TradingMode.LIVE,
                live_trading_enabled=False,
                version="test",
            )

    def test_config_accepts_paper_mode(self) -> None:
        """Test that SystemConfig accepts paper mode."""
        config = SystemConfig(
            trading_mode=TradingMode.PAPER,
            live_trading_enabled=False,
            version="test",
        )
        assert config.trading_mode == TradingMode.PAPER
        assert config.live_trading_enabled is False
        assert config.version == "test"
