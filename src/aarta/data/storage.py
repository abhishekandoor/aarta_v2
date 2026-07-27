"""Content-addressed storage for immutable historical data with atomic operations."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aarta.domain.models import Bar


@dataclass(frozen=True)
class StorageManifest:
    """Manifest for content-addressed storage.

    Attributes:
        storage_id: Unique identifier for this storage instance.
        root_path: Root directory path.
        bar_count: Total number of bars stored.
        instrument_ids: Set of instrument IDs in storage.
        content_hashes: Set of all content hashes.
        created_at: UTC timestamp of storage creation.
        updated_at: UTC timestamp of last update.
        manifest_hash: SHA-256 hash of this manifest (excluding itself).
    """

    storage_id: str
    root_path: str
    bar_count: int
    instrument_ids: list[str]
    content_hashes: list[str]
    created_at: str
    updated_at: str
    manifest_hash: str = ""

    def __post_init__(self) -> None:
        # Compute manifest hash if not provided
        if not self.manifest_hash:
            data = {
                "storage_id": self.storage_id,
                "root_path": self.root_path,
                "bar_count": self.bar_count,
                "instrument_ids": sorted(self.instrument_ids),
                "content_hashes": sorted(self.content_hashes),
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
            canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
            object.__setattr__(
                self, "manifest_hash", hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            )


@dataclass(frozen=True)
class StoredBar:
    """A bar with its content address metadata.

    Attributes:
        bar: The bar data.
        content_hash: SHA-256 hash of the bar's canonical representation.
        storage_path: Path where the bar is stored.
        stored_at: UTC timestamp when stored.
    """

    bar: Bar
    content_hash: str
    storage_path: str
    stored_at: str


class ContentAddressedStorage:
    """Content-addressed storage for historical bar data.

    Features:
    - Bars stored by SHA-256 hash of their canonical JSON representation
    - Atomic write operations using temp files and renames
    - Duplicate detection via content hash
    - Immutable storage (no updates, only appends)
    - Manifest tracking for integrity verification
    - Checksums for corruption detection
    """

    def __init__(self, root_path: Path | str, storage_id: str | None = None) -> None:
        """Initialize content-addressed storage.

        Args:
            root_path: Root directory for storage.
            storage_id: Optional storage identifier (generated if not provided).
        """
        self._root = Path(root_path)
        self._bars_dir = self._root / "bars"
        self._manifest_path = self._root / "manifest.json"
        self._storage_id = storage_id or hashlib.sha256(
            str(datetime.now(timezone.utc).isoformat()).encode("utf-8")
        ).hexdigest()[:16]

        # Internal state (mutable for building, but exposed immutably)
        self._bars: dict[str, StoredBar] = {}  # hash -> StoredBar
        self._instrument_bars: dict[str, list[str]] = {}  # instrument_id -> [hashes]
        self._created_at = datetime.now(timezone.utc).isoformat()
        self._updated_at = self._created_at

    @property
    def root(self) -> Path:
        """Root directory of the storage."""
        return self._root

    @property
    def storage_id(self) -> str:
        """Unique storage identifier."""
        return self._storage_id

    def _compute_content_hash(self, bar: Bar) -> str:
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

    def _get_bar_path(self, content_hash: str) -> Path:
        """Get the file path for a content hash.

        Uses first 2 characters as subdirectory for filesystem efficiency.
        """
        prefix = content_hash[:2]
        return self._bars_dir / prefix / content_hash

    def initialize(self) -> None:
        """Initialize the storage directory structure."""
        self._root.mkdir(parents=True, exist_ok=True)
        self._bars_dir.mkdir(exist_ok=True)

    def store_bar(self, bar: Bar) -> StoredBar:
        """Store a bar atomically using content-addressed storage.

        Args:
            bar: The bar to store.

        Returns:
            StoredBar with metadata.

        Raises:
            ValueError: If storage is not initialized.
        """
        if not self._root.exists():
            raise ValueError("Storage not initialized. Call initialize() first.")

        content_hash = self._compute_content_hash(bar)

        # Check if already stored (deduplication)
        if content_hash in self._bars:
            return self._bars[content_hash]

        # Create storage path
        bar_path = self._get_bar_path(content_hash)
        bar_path.parent.mkdir(exist_ok=True)

        # Write atomically using temp file and rename
        bar_data = {
            "instrument_id": bar.instrument_id,
            "timestamp": bar.timestamp,
            "open": str(bar.open),
            "high": str(bar.high),
            "low": str(bar.low),
            "close": str(bar.close),
            "volume": str(bar.volume),
        }
        canonical_json = json.dumps(bar_data, sort_keys=True, indent=2)

        # Write to temp file first, then atomic rename
        fd, temp_path = tempfile.mkstemp(dir=bar_path.parent, suffix=".tmp")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(canonical_json)
            # Atomic rename
            Path(temp_path).rename(bar_path)
        except Exception:
            # Clean up temp file on failure
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass
            raise

        stored_at = datetime.now(timezone.utc).isoformat()
        stored_bar = StoredBar(
            bar=bar,
            content_hash=content_hash,
            storage_path=str(bar_path),
            stored_at=stored_at,
        )

        # Update internal state
        self._bars[content_hash] = stored_bar

        # Track by instrument
        if bar.instrument_id not in self._instrument_bars:
            self._instrument_bars[bar.instrument_id] = []
        self._instrument_bars[bar.instrument_id].append(content_hash)

        self._updated_at = stored_at

        return stored_bar

    def store_bars(self, bars: list[Bar]) -> list[StoredBar]:
        """Store multiple bars atomically.

        Args:
            bars: List of bars to store.

        Returns:
            List of StoredBar objects.
        """
        results: list[StoredBar] = []
        for bar in bars:
            stored = self.store_bar(bar)
            results.append(stored)
        return results

    def get_bar(self, content_hash: str) -> StoredBar | None:
        """Retrieve a bar by its content hash.

        Args:
            content_hash: The SHA-256 hash of the bar.

        Returns:
            StoredBar or None if not found.
        """
        return self._bars.get(content_hash)

    def get_bars_for_instrument(self, instrument_id: str) -> list[Bar]:
        """Get all bars for an instrument, sorted by timestamp.

        Args:
            instrument_id: The instrument identifier.

        Returns:
            List of bars sorted chronologically.
        """
        hashes = self._instrument_bars.get(instrument_id, [])
        bars = [self._bars[h].bar for h in hashes if h in self._bars]
        # Sort by timestamp
        bars.sort(key=lambda b: b.timestamp)
        return bars

    def has_content(self, content_hash: str) -> bool:
        """Check if content exists in storage.

        Args:
            content_hash: The hash to check.

        Returns:
            True if the content exists.
        """
        return content_hash in self._bars

    def verify_integrity(self, content_hash: str) -> bool:
        """Verify the integrity of a stored bar.

        Args:
            content_hash: The hash to verify.

        Returns:
            True if the stored content matches its hash.
        """
        stored = self._bars.get(content_hash)
        if stored is None:
            return False

        bar_path = Path(stored.storage_path)
        if not bar_path.exists():
            return False

        try:
            with open(bar_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Recompute hash
            canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
            computed_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

            return computed_hash == content_hash
        except Exception:
            return False

    def get_manifest(self) -> StorageManifest:
        """Get the current storage manifest.

        Returns:
            StorageManifest with current state.
        """
        all_hashes = list(self._bars.keys())
        instrument_ids = list(self._instrument_bars.keys())

        return StorageManifest(
            storage_id=self._storage_id,
            root_path=str(self._root),
            bar_count=len(self._bars),
            instrument_ids=instrument_ids,
            content_hashes=all_hashes,
            created_at=self._created_at,
            updated_at=self._updated_at,
        )

    def save_manifest(self) -> None:
        """Save the manifest to disk atomically."""
        manifest = self.get_manifest()
        manifest_data = {
            "storage_id": manifest.storage_id,
            "root_path": manifest.root_path,
            "bar_count": manifest.bar_count,
            "instrument_ids": manifest.instrument_ids,
            "content_hashes": manifest.content_hashes,
            "created_at": manifest.created_at,
            "updated_at": manifest.updated_at,
            "manifest_hash": manifest.manifest_hash,
        }
        canonical_json = json.dumps(manifest_data, sort_keys=True, indent=2)

        # Atomic write
        fd, temp_path = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(canonical_json)
            Path(temp_path).rename(self._manifest_path)
        except Exception:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                raise

    @classmethod
    def load_from_manifest(cls, manifest_path: Path | str) -> ContentAddressedStorage:
        """Load storage state from a manifest file.

        Args:
            manifest_path: Path to the manifest file.

        Returns:
            ContentAddressedStorage with loaded state.
        """
        manifest_path = Path(manifest_path)
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        storage = cls(root_path=data["root_path"], storage_id=data["storage_id"])
        storage._created_at = data["created_at"]
        storage._updated_at = data["updated_at"]

        # Note: This loads the manifest metadata only.
        # Actual bar data would need to be re-loaded from files.
        # For now, we track the metadata but bars must be re-ingested.

        return storage
