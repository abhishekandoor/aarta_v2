"""Configuration constants and settings for AARTA."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class TradingMode(Enum):
    """Trading mode enumeration."""

    PAPER = "paper"
    LIVE = "live"  # Reserved for future use, currently disabled


@dataclass(frozen=True)
class SystemConfig:
    """System configuration.

    All fields are immutable. Live trading is explicitly disabled.
    """

    trading_mode: TradingMode
    live_trading_enabled: bool
    version: str

    def __post_init__(self) -> None:
        """Validate configuration constraints."""
        if self.live_trading_enabled:
            raise RuntimeError(
                "Live trading is not permitted in this version of AARTA."
            )
        if self.trading_mode == TradingMode.LIVE:
            raise RuntimeError(
                "Live trading mode is not permitted in this version of AARTA."
            )


# Default system configuration - paper only
DEFAULT_CONFIG: Final[SystemConfig] = SystemConfig(
    trading_mode=TradingMode.PAPER,
    live_trading_enabled=False,
    version="0.1.0",
)
