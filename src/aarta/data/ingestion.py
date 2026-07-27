"""Provider-neutral historical data ingestion with validation and provenance tracking."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from aarta.domain.models import Bar, Instrument


@dataclass(frozen=True)
class IngestionResult:
    """Result of ingesting a batch of bar data.

    Attributes:
        instrument_id: The instrument identifier.
        bars_ingested: Number of bars successfully ingested.
        duplicates_detected: Number of duplicate bars skipped.
        conflicts_detected: Number of conflicting bars rejected.
        invalid_bars: Number of bars that failed validation.
        content_hashes: List of SHA-256 hashes for ingested bars.
        manifest_hash: SHA-256 hash of the ingestion manifest.
        ingested_at: UTC timestamp of ingestion.
    """

    instrument_id: str
    bars_ingested: int
    duplicates_detected: int
    conflicts_detected: int
    invalid_bars: int
    content_hashes: list[str] = field(default_factory=list)
    manifest_hash: str = ""
    ingested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.bars_ingested < 0:
            raise ValueError("bars_ingested must be non-negative")
        if self.duplicates_detected < 0:
            raise ValueError("duplicates_detected must be non-negative")
        if self.conflicts_detected < 0:
            raise ValueError("conflicts_detected must be non-negative")
        if self.invalid_bars < 0:
            raise ValueError("invalid_bars must be non-negative")


class DataIngestor:
    """Provider-neutral historical data ingestor.

    Responsibilities:
    - Accept bar data from any provider format
    - Validate bar structure and values
    - Detect duplicates by (instrument_id, timestamp)
    - Detect conflicting bars (same timestamp, different OHLCV)
    - Compute content hashes for each bar
    - Produce immutable ingestion results
    """

    def __init__(self) -> None:
        self._ingested_keys: set[tuple[str, str]] = set()
        self._bar_hashes: dict[tuple[str, str], str] = {}

    def _compute_bar_hash(self, bar: Bar) -> str:
        """Compute SHA-256 hash of a bar's canonical JSON representation."""
        canonical = json.dumps(
            {
                "instrument_id": bar.instrument_id,
                "timestamp": bar.timestamp,
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": str(bar.volume),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _validate_bar(self, bar: Bar) -> bool:
        """Validate bar structure and values."""
        # Basic OHLCV constraints
        if bar.low > bar.high:
            return False
        if bar.open < bar.low or bar.open > bar.high:
            return False
        if bar.close < bar.low or bar.close > bar.high:
            return False
        if bar.volume < 0:
            return False
        if any(p < Decimal(0) for p in [bar.open, bar.high, bar.low, bar.close]):
            return False
        return True

    def ingest_bars(
        self,
        bars: Iterable[Bar],
        existing_keys: set[tuple[str, str]] | None = None,
        existing_hashes: dict[tuple[str, str], str] | None = None,
    ) -> IngestionResult:
        """Ingest a batch of bars, detecting duplicates and conflicts.

        Args:
            bars: Iterable of Bar objects to ingest.
            existing_keys: Previously ingested (instrument_id, timestamp) pairs.
            existing_hashes: Previously ingested bar hashes by key.

        Returns:
            IngestionResult with counts and content hashes.
        """
        known_keys = existing_keys if existing_keys is not None else self._ingested_keys
        known_hashes = existing_hashes if existing_hashes is not None else self._bar_hashes

        ingested = 0
        duplicates = 0
        conflicts = 0
        invalid = 0
        content_hashes: list[str] = []

        for bar in bars:
            key = (bar.instrument_id, bar.timestamp)
            bar_hash = self._compute_bar_hash(bar)

            # Validate bar structure
            if not self._validate_bar(bar):
                invalid += 1
                continue

            # Check for duplicate
            if key in known_keys:
                if known_hashes.get(key) == bar_hash:
                    # Exact duplicate
                    duplicates += 1
                else:
                    # Conflict: same timestamp, different data
                    conflicts += 1
                continue

            # Accept the bar
            ingested += 1
            content_hashes.append(bar_hash)
            # Note: We don't mutate known_keys/hashes here to maintain immutability
            # The caller is responsible for updating their state

        # Compute manifest hash
        manifest_data = json.dumps(
            {
                "bars_ingested": ingested,
                "content_hashes": sorted(content_hashes),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        manifest_hash = hashlib.sha256(manifest_data.encode("utf-8")).hexdigest()

        return IngestionResult(
            instrument_id=bars[0].instrument_id if bars else "",
            bars_ingested=ingested,
            duplicates_detected=duplicates,
            conflicts_detected=conflicts,
            invalid_bars=invalid,
            content_hashes=content_hashes,
            manifest_hash=manifest_hash,
        )

    @staticmethod
    def parse_csv_row(
        row: dict[str, str],
        instrument: Instrument,
        timestamp_column: str = "timestamp",
        open_column: str = "open",
        high_column: str = "high",
        low_column: str = "low",
        close_column: str = "close",
        volume_column: str = "volume",
    ) -> Bar | None:
        """Parse a CSV row into a Bar object.

        Args:
            row: Dictionary representing a CSV row.
            instrument: The instrument for this bar.
            timestamp_column: Column name for timestamp.
            open_column: Column name for open price.
            high_column: Column name for high price.
            low_column: Column name for low price.
            close_column: Column name for close price.
            volume_column: Column name for volume.

        Returns:
            Bar object or None if parsing fails.
        """
        try:
            timestamp_str = row.get(timestamp_column, "")
            # Parse ISO 8601 timestamp
            if not timestamp_str:
                return None
            ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            return Bar(
                instrument_id=instrument.id,
                timestamp=ts.isoformat(),
                open=Decimal(row[open_column]),
                high=Decimal(row[high_column]),
                low=Decimal(row[low_column]),
                close=Decimal(row[close_column]),
                volume=Decimal(row.get(volume_column, "0")),
            )
        except (KeyError, ValueError, TypeError):
            return None
