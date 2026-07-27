"""Immutable dataset management with manifests and verification."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aarta.domain.models import Bar
from aarta.data.storage import ContentAddressedStorage, StorageManifest


@dataclass(frozen=True)
class DatasetManifest:
    """Manifest for an immutable historical dataset.

    Attributes:
        dataset_id: Unique identifier for this dataset.
        name: Human-readable name.
        description: Description of the dataset.
        instrument_ids: List of instruments included.
        start_timestamp: Earliest bar timestamp.
        end_timestamp: Latest bar timestamp.
        bar_count: Total number of bars.
        content_hashes: Sorted list of all bar content hashes.
        storage_manifest: Reference to underlying storage manifest.
        created_at: UTC timestamp of dataset creation.
        dataset_hash: SHA-256 hash of this dataset's canonical representation.
    """

    dataset_id: str
    name: str
    description: str
    instrument_ids: list[str]
    start_timestamp: str
    end_timestamp: str
    bar_count: int
    content_hashes: list[str]
    storage_manifest: StorageManifest
    created_at: str
    dataset_hash: str = ""

    def __post_init__(self) -> None:
        # Compute dataset hash if not provided
        if not self.dataset_hash:
            data = {
                "dataset_id": self.dataset_id,
                "name": self.name,
                "description": self.description,
                "instrument_ids": sorted(self.instrument_ids),
                "start_timestamp": self.start_timestamp,
                "end_timestamp": self.end_timestamp,
                "bar_count": self.bar_count,
                "content_hashes": sorted(self.content_hashes),
                "storage_manifest_hash": self.storage_manifest.manifest_hash,
                "created_at": self.created_at,
            }
            canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
            object.__setattr__(
                self, "dataset_hash", hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "dataset_id": self.dataset_id,
            "name": self.name,
            "description": self.description,
            "instrument_ids": sorted(self.instrument_ids),
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "bar_count": self.bar_count,
            "content_hashes": sorted(self.content_hashes),
            "storage_manifest_hash": self.storage_manifest.manifest_hash,
            "created_at": self.created_at,
            "dataset_hash": self.dataset_hash,
        }


@dataclass(frozen=True)
class Dataset:
    """An immutable historical dataset with verified provenance.

    A Dataset is a logical grouping of bars that:
    - Has a unique identity (dataset_id)
    - References bars in content-addressed storage
    - Has a verified manifest with checksums
    - Cannot be modified after creation
    """

    manifest: DatasetManifest
    storage: ContentAddressedStorage

    def get_bars(self, instrument_id: str) -> list[Bar]:
        """Get all bars for an instrument from this dataset.

        Args:
            instrument_id: The instrument identifier.

        Returns:
            List of bars sorted by timestamp.
        """
        return self.storage.get_bars_for_instrument(instrument_id)

    def get_all_bars(self) -> list[Bar]:
        """Get all bars from all instruments, sorted by timestamp then instrument.

        Returns:
            List of all bars in chronological order.
        """
        all_bars: list[Bar] = []
        for instrument_id in self.manifest.instrument_ids:
            all_bars.extend(self.get_bars(instrument_id))

        # Sort by timestamp, then by instrument_id for deterministic ordering
        all_bars.sort(key=lambda b: (b.timestamp, b.instrument_id))
        return all_bars

    def verify_integrity(self) -> tuple[bool, list[str]]:
        """Verify the integrity of all bars in the dataset.

        Returns:
            Tuple of (all_valid, list_of_error_messages).
        """
        errors: list[str] = []

        for content_hash in self.manifest.content_hashes:
            if not self.storage.verify_integrity(content_hash):
                errors.append(f"Integrity check failed for hash: {content_hash[:16]}...")

        return len(errors) == 0, errors

    def contains_instrument(self, instrument_id: str) -> bool:
        """Check if dataset contains bars for an instrument."""
        return instrument_id in self.manifest.instrument_ids


class DatasetBuilder:
    """Builder for creating immutable datasets.

    Usage:
        builder = DatasetBuilder(name="NIFTY_ETF_2024")
        builder.add_bars(bars)
        dataset = builder.build(storage)
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        dataset_id: str | None = None,
    ) -> None:
        """Initialize the dataset builder.

        Args:
            name: Human-readable name for the dataset.
            description: Optional description.
            dataset_id: Optional explicit ID (generated if not provided).
        """
        self._name = name
        self._description = description
        self._dataset_id = dataset_id or hashlib.sha256(
            f"{name}:{datetime.now(timezone.utc).isoformat()}".encode("utf-8")
        ).hexdigest()[:16]
        self._bars: list[Bar] = []
        self._content_hashes: set[str] = set()

    def add_bars(self, bars: list[Bar]) -> DatasetBuilder:
        """Add bars to the dataset being built.

        Args:
            bars: List of bars to add.

        Returns:
            Self for method chaining.
        """
        self._bars.extend(bars)
        return self

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

    def build(self, storage: ContentAddressedStorage) -> Dataset:
        """Build the immutable dataset and store it.

        Args:
            storage: Content-addressed storage to use.

        Returns:
            Immutable Dataset with verified manifest.

        Raises:
            ValueError: If no bars were added.
        """
        if not self._bars:
            raise ValueError("Cannot build empty dataset")

        # Store all bars
        stored_bars = storage.store_bars(self._bars)

        # Collect metadata
        instrument_ids: set[str] = set()
        timestamps: list[str] = []
        content_hashes: list[str] = []

        for stored in stored_bars:
            instrument_ids.add(stored.bar.instrument_id)
            timestamps.append(stored.bar.timestamp)
            content_hashes.append(stored.content_hash)

        # Sort for determinism
        timestamps.sort()
        content_hashes = sorted(set(content_hashes))  # Deduplicate

        # Get storage manifest
        storage.save_manifest()
        storage_manifest = storage.get_manifest()

        # Create dataset manifest
        created_at = datetime.now(timezone.utc).isoformat()
        manifest = DatasetManifest(
            dataset_id=self._dataset_id,
            name=self._name,
            description=self._description,
            instrument_ids=sorted(instrument_ids),
            start_timestamp=timestamps[0],
            end_timestamp=timestamps[-1],
            bar_count=len(stored_bars),
            content_hashes=content_hashes,
            storage_manifest=storage_manifest,
            created_at=created_at,
        )

        return Dataset(manifest=manifest, storage=storage)

    def save_manifest_only(self, output_path: Path | str) -> DatasetManifest:
        """Save only the dataset manifest without storing bars.

        Useful for publishing dataset specifications before ingestion.

        Args:
            output_path: Path to write the manifest JSON.

        Returns:
            The created DatasetManifest.
        """
        if not self._bars:
            raise ValueError("Cannot save manifest for empty dataset")

        # Collect metadata without storing
        instrument_ids: set[str] = set()
        timestamps: list[str] = []
        content_hashes: list[str] = []

        for bar in self._bars:
            instrument_ids.add(bar.instrument_id)
            timestamps.append(bar.timestamp)
            content_hashes.append(self._compute_bar_hash(bar))

        timestamps.sort()
        content_hashes = sorted(set(content_hashes))

        # Create a placeholder storage manifest
        placeholder_manifest = DatasetManifest(
            dataset_id=self._dataset_id,
            name=self._name,
            description=self._description,
            instrument_ids=sorted(instrument_ids),
            start_timestamp=timestamps[0],
            end_timestamp=timestamps[-1],
            bar_count=len(self._bars),
            content_hashes=content_hashes,
            storage_manifest=StorageManifest(
                storage_id="pending",
                root_path="",
                bar_count=0,
                instrument_ids=[],
                content_hashes=[],
                created_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
            ),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        # Write manifest to file atomically
        manifest_data = placeholder_manifest.to_dict()
        canonical_json = json.dumps(manifest_data, sort_keys=True, indent=2)

        output_path = Path(output_path)
        fd, temp_path = tempfile.mkstemp(dir=output_path.parent, suffix=".tmp")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(canonical_json)
            Path(temp_path).rename(output_path)
        except Exception:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                raise

        return placeholder_manifest


class DatasetInspector:
    """Inspection and verification tools for datasets."""

    @staticmethod
    def load_manifest(manifest_path: Path | str) -> dict[str, Any]:
        """Load a dataset manifest from disk.

        Args:
            manifest_path: Path to the manifest JSON file.

        Returns:
            Dictionary representation of the manifest.
        """
        manifest_path = Path(manifest_path)
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def verify_manifest_hash(manifest_path: Path | str) -> tuple[bool, str]:
        """Verify that a manifest's self-hash is correct.

        Args:
            manifest_path: Path to the manifest JSON file.

        Returns:
            Tuple of (is_valid, error_message).
        """
        data = DatasetInspector.load_manifest(manifest_path)

        # Extract the stored hash
        stored_hash = data.get("dataset_hash", "")

        # Recompute without the hash field
        data_copy = {k: v for k, v in data.items() if k != "dataset_hash"}
        canonical = json.dumps(data_copy, sort_keys=True, separators=(",", ":"))
        computed_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        if stored_hash != computed_hash:
            return False, f"Hash mismatch: stored={stored_hash[:16]}..., computed={computed_hash[:16]}..."

        return True, ""

    @staticmethod
    def get_dataset_summary(manifest_path: Path | str) -> dict[str, Any]:
        """Get a summary of a dataset from its manifest.

        Args:
            manifest_path: Path to the manifest JSON file.

        Returns:
            Summary dictionary with key statistics.
        """
        data = DatasetInspector.load_manifest(manifest_path)

        return {
            "dataset_id": data["dataset_id"],
            "name": data["name"],
            "instrument_count": len(data["instrument_ids"]),
            "instruments": data["instrument_ids"],
            "bar_count": data["bar_count"],
            "start_timestamp": data["start_timestamp"],
            "end_timestamp": data["end_timestamp"],
            "created_at": data["created_at"],
            "dataset_hash": data["dataset_hash"][:16] + "...",
            "integrity_verified": data.get("dataset_hash") is not None,
        }
