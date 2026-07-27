"""Backtest result manifest and storage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BacktestResultManifest:
    """Immutable manifest of backtest results."""

    strategy_id: str
    dataset_id: str
    start_time: str  # ISO 8601 UTC
    end_time: str  # ISO 8601 UTC
    bars_processed: int
    funnel_stats: dict[str, int]
    final_equity: str
    total_return: str
    max_drawdown: str
    total_fees: str
    total_slippage: str
    num_fills: int
    num_trades: int
    win_rate: str
    profit_factor: str
    sharpe_ratio: str
    sortino_ratio: str
    calmar_ratio: str
    trades: list[dict[str, Any]] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    config_hash: str = ""
    result_hash: str = ""

    def __post_init__(self) -> None:
        # Compute config hash
        config_data = {
            "strategy_id": self.strategy_id,
            "dataset_id": self.dataset_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }
        config_json = json.dumps(config_data, sort_keys=True, separators=(",", ":"))
        object.__setattr__(self, "config_hash", hashlib.sha256(config_json.encode()).hexdigest())

        # Compute result hash
        result_data = {
            "final_equity": self.final_equity,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "funnel_stats": self.funnel_stats,
            "num_fills": self.num_fills,
            "num_trades": self.num_trades,
        }
        result_json = json.dumps(result_data, sort_keys=True, separators=(",", ":"))
        object.__setattr__(self, "result_hash", hashlib.sha256(result_json.encode()).hexdigest())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "strategy_id": self.strategy_id,
            "dataset_id": self.dataset_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "bars_processed": self.bars_processed,
            "funnel_stats": self.funnel_stats,
            "final_equity": self.final_equity,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "total_fees": self.total_fees,
            "total_slippage": self.total_slippage,
            "num_fills": self.num_fills,
            "num_trades": self.num_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "trades": self.trades,
            "fills": self.fills,
            "config_hash": self.config_hash,
            "result_hash": self.result_hash,
        }

    def to_json(self) -> str:
        """Serialize to canonical JSON."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


class ResultStorage:
    """Atomic storage for backtest results."""

    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_result_path(self, manifest: BacktestResultManifest) -> Path:
        """Get the storage path for a result."""
        return self.base_path / f"{manifest.result_hash}.json"

    def save(self, manifest: BacktestResultManifest) -> Path:
        """Atomically save a result manifest."""
        result_path = self._get_result_path(manifest)
        temp_path = result_path.with_suffix(".tmp")

        # Write to temp file first
        content = manifest.to_json()
        temp_path.write_text(content, encoding="utf-8")

        # Atomic rename
        temp_path.rename(result_path)

        return result_path

    def load(self, result_hash: str) -> BacktestResultManifest | None:
        """Load a result manifest by hash."""
        result_path = self.base_path / f"{result_hash}.json"
        if not result_path.exists():
            return None

        data = json.loads(result_path.read_text(encoding="utf-8"))
        return BacktestResultManifest(**data)

    def exists(self, manifest: BacktestResultManifest) -> bool:
        """Check if a result already exists."""
        return self._get_result_path(manifest).exists()

    def list_results(self) -> list[str]:
        """List all result hashes."""
        return [p.stem for p in self.base_path.glob("*.json")]
