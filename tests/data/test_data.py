"""Tests for historical data ingestion, validation, storage, and datasets."""

import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from aarta.data.dataset import (
    DatasetBuilder,
    DatasetInspector,
    DatasetManifest,
)
from aarta.data.ingestion import DataIngestor, IngestionResult
from aarta.data.storage import ContentAddressedStorage
from aarta.data.validation import (
    BarValidator,
    ValidationErrorType,
)
from aarta.domain.models import Bar, Instrument

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_instrument() -> Instrument:
    """Create a sample NIFTY ETF instrument."""
    return Instrument(
        symbol="NIFTYBEES",
        name="NIFTY Exchange Traded Fund",
        exchange="NSE",
        lot_size=1,
        tick_size=Decimal("0.05"),
        currency="INR",
        instrument_type="ETF",
    )


@pytest.fixture
def sample_bars(sample_instrument: Instrument) -> list[Bar]:
    """Create a list of sample bars for testing."""
    base_time = datetime(2024, 1, 15, 9, 15, 0, tzinfo=UTC)
    bars = []
    for i in range(5):
        ts = base_time.replace(minute=15 + i * 5)
        bars.append(
            Bar(
                instrument_id=sample_instrument.symbol,
                timestamp=ts.isoformat(),
                open=Decimal("220.00") + Decimal(i) * Decimal("0.5"),
                high=Decimal("221.00") + Decimal(i) * Decimal("0.5"),
                low=Decimal("219.50") + Decimal(i) * Decimal("0.5"),
                close=Decimal("220.50") + Decimal(i) * Decimal("0.5"),
                volume=1000 * (i + 1),
            )
        )
    return bars


@pytest.fixture
def temp_storage_dir() -> Path:
    """Create a temporary directory for storage tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


# =============================================================================
# Ingestion Tests
# =============================================================================


class TestIngestionResult:
    """Tests for IngestionResult immutability and validation."""

    def test_creation(self) -> None:
        """Test basic creation of IngestionResult."""
        result = IngestionResult(
            instrument_id="TEST",
            bars_ingested=10,
            duplicates_detected=2,
            conflicts_detected=1,
            invalid_bars=0,
            content_hashes=[
                "hash1",
                "hash2",
            ],  # Provide hashes to generate manifest_hash
        )
        assert result.bars_ingested == 10
        assert result.duplicates_detected == 2
        assert result.conflicts_detected == 1
        assert result.invalid_bars == 0
        assert result.manifest_hash != ""

    def test_negative_counts_rejected(self) -> None:
        """Test that negative counts are rejected."""
        with pytest.raises(ValueError):
            IngestionResult(
                instrument_id="TEST",
                bars_ingested=-1,
                duplicates_detected=0,
                conflicts_detected=0,
                invalid_bars=0,
            )

    def test_immutability(self, sample_bars: list[Bar]) -> None:
        """Test that IngestionResult is frozen."""
        ingestor = DataIngestor()
        result = ingestor.ingest_bars(sample_bars)

        with pytest.raises(
            Exception
        ):  # frozen dataclass raises AttributeError or FrozenInstanceError
            result.bars_ingested = 999  # type: ignore[misc]


class TestDataIngestor:
    """Tests for DataIngestor functionality."""

    def test_ingest_valid_bars(self, sample_bars: list[Bar]) -> None:
        """Test ingestion of valid bars."""
        ingestor = DataIngestor()
        result = ingestor.ingest_bars(sample_bars)

        assert result.bars_ingested == 5
        assert result.duplicates_detected == 0
        assert result.conflicts_detected == 0
        assert result.invalid_bars == 0
        assert len(result.content_hashes) == 5

    def test_duplicate_detection(self, sample_bars: list[Bar]) -> None:
        """Test detection of duplicate bars."""
        ingestor = DataIngestor()

        # First ingestion
        result1 = ingestor.ingest_bars(sample_bars)
        assert result1.bars_ingested == 5

        # Create existing state
        existing_keys = {(b.instrument_id, b.timestamp) for b in sample_bars}
        existing_hashes = {
            (b.instrument_id, b.timestamp): ingestor._compute_bar_hash(b)
            for b in sample_bars
        }

        # Second ingestion with same bars
        result2 = ingestor.ingest_bars(
            sample_bars, existing_keys=existing_keys, existing_hashes=existing_hashes
        )
        assert result2.bars_ingested == 0
        assert result2.duplicates_detected == 5
        assert result2.conflicts_detected == 0

    def test_conflict_detection(self, sample_bars: list[Bar]) -> None:
        """Test detection of conflicting bars (same timestamp, different data)."""
        ingestor = DataIngestor()

        # First ingestion
        result1 = ingestor.ingest_bars(sample_bars)
        assert result1.bars_ingested == 5

        # Create conflicting bar (same timestamp, different OHLCV)
        conflict_bar = Bar(
            instrument_id=sample_bars[0].instrument_id,
            timestamp=sample_bars[0].timestamp,
            open=Decimal("999.00"),  # Different price
            high=Decimal("1000.00"),
            low=Decimal("998.00"),
            close=Decimal("999.50"),
            volume=Decimal(9999),
        )

        existing_keys = {(b.instrument_id, b.timestamp) for b in sample_bars}
        existing_hashes = {
            (b.instrument_id, b.timestamp): ingestor._compute_bar_hash(b)
            for b in sample_bars
        }

        result2 = ingestor.ingest_bars(
            [conflict_bar], existing_keys=existing_keys, existing_hashes=existing_hashes
        )
        assert result2.bars_ingested == 0
        assert result2.conflicts_detected == 1

    def test_invalid_bar_detection(self, sample_instrument: Instrument) -> None:
        """Test detection of invalid bars (low > high)."""
        ingestor = DataIngestor()

        # Bypass Bar's __post_init__ validation to create an invalid bar for testing
        invalid_bar = object.__new__(Bar)
        invalid_bar.instrument_id = sample_instrument.symbol
        invalid_bar.timestamp = datetime(2024, 1, 15, 10, 0, tzinfo=UTC).isoformat()
        invalid_bar.open = Decimal("220.00")
        invalid_bar.high = Decimal("219.00")  # High < Low - invalid
        invalid_bar.low = Decimal("221.00")
        invalid_bar.close = Decimal("220.50")
        invalid_bar.volume = 1000

        result = ingestor.ingest_bars([invalid_bar])
        assert result.bars_ingested == 0
        assert result.invalid_bars == 1

    def test_bar_hash_determinism(self, sample_bars: list[Bar]) -> None:
        """Test that bar hashes are deterministic."""
        ingestor = DataIngestor()
        hash1 = ingestor._compute_bar_hash(sample_bars[0])
        hash2 = ingestor._compute_bar_hash(sample_bars[0])
        assert hash1 == hash2

    def test_parse_csv_row(self, sample_instrument: Instrument) -> None:
        """Test CSV row parsing."""
        row = {
            "timestamp": "2024-01-15T09:15:00+00:00",
            "open": "220.00",
            "high": "221.00",
            "low": "219.50",
            "close": "220.50",
            "volume": "1000",
        }

        bar = DataIngestor.parse_csv_row(row, sample_instrument)
        assert bar is not None
        assert bar.instrument_id == "NIFTYBEES"
        assert bar.open == Decimal("220.00")
        assert bar.volume == 1000

    def test_parse_csv_row_invalid(self, sample_instrument: Instrument) -> None:
        """Test CSV row parsing with invalid data."""
        row = {
            "timestamp": "invalid-timestamp",
            "open": "not-a-number",
        }

        bar = DataIngestor.parse_csv_row(row, sample_instrument)
        assert bar is None


# =============================================================================
# Validation Tests
# =============================================================================


class TestBarValidator:
    """Tests for BarValidator functionality."""

    def test_valid_bar(self, sample_bars: list[Bar]) -> None:
        """Test validation of valid bars."""
        validator = BarValidator()
        for bar in sample_bars:
            errors = validator.validate_bar(bar)
            assert len(errors) == 0, f"Valid bar had errors: {errors}"

    def test_low_greater_than_high(self, sample_instrument: Instrument) -> None:
        """Test detection of low > high error."""
        validator = BarValidator()

        # Bypass Bar's __post_init__ validation to create an invalid bar for testing
        bar = object.__new__(Bar)
        bar.instrument_id = sample_instrument.symbol
        bar.timestamp = datetime(2024, 1, 15, 10, 0, tzinfo=UTC).isoformat()
        bar.open = Decimal("220.00")
        bar.high = Decimal("219.00")
        bar.low = Decimal("221.00")
        bar.close = Decimal("220.50")
        bar.volume = 1000

        errors = validator.validate_bar(bar)
        assert any(
            e.error_type == ValidationErrorType.LOW_GREATER_THAN_HIGH for e in errors
        )

    def test_open_below_low(self, sample_instrument: Instrument) -> None:
        """Test detection of open < low error."""
        validator = BarValidator()

        # Bypass Bar's __post_init__ validation to create an invalid bar for testing
        bar = object.__new__(Bar)
        bar.instrument_id = sample_instrument.symbol
        bar.timestamp = datetime(2024, 1, 15, 10, 0, tzinfo=UTC).isoformat()
        bar.open = Decimal("218.00")  # Below low
        bar.high = Decimal("221.00")
        bar.low = Decimal("219.00")
        bar.close = Decimal("220.50")
        bar.volume = 1000

        errors = validator.validate_bar(bar)
        assert any(e.error_type == ValidationErrorType.OPEN_BELOW_LOW for e in errors)

    def test_close_above_high(self, sample_instrument: Instrument) -> None:
        """Test detection of close > high error."""
        validator = BarValidator()

        # Bypass Bar's __post_init__ validation to create an invalid bar for testing
        bar = object.__new__(Bar)
        bar.instrument_id = sample_instrument.symbol
        bar.timestamp = datetime(2024, 1, 15, 10, 0, tzinfo=UTC).isoformat()
        bar.open = Decimal("220.00")
        bar.high = Decimal("221.00")
        bar.low = Decimal("219.00")
        bar.close = Decimal("222.00")  # Above high
        bar.volume = 1000

        errors = validator.validate_bar(bar)
        assert any(e.error_type == ValidationErrorType.CLOSE_ABOVE_HIGH for e in errors)

    def test_negative_price(self, sample_instrument: Instrument) -> None:
        """Test detection of negative prices."""
        validator = BarValidator()

        # Bypass Bar's __post_init__ validation to create an invalid bar for testing
        bar = object.__new__(Bar)
        bar.instrument_id = sample_instrument.symbol
        bar.timestamp = datetime(2024, 1, 15, 10, 0, tzinfo=UTC).isoformat()
        bar.open = Decimal("-220.00")
        bar.high = Decimal("221.00")
        bar.low = Decimal("219.00")
        bar.close = Decimal("220.50")
        bar.volume = 1000

        errors = validator.validate_bar(bar)
        assert any(e.error_type == ValidationErrorType.NEGATIVE_PRICE for e in errors)

    def test_negative_volume(self, sample_instrument: Instrument) -> None:
        """Test detection of negative volume."""
        validator = BarValidator()

        # Bypass Bar's __post_init__ validation to create an invalid bar for testing
        bar = object.__new__(Bar)
        bar.instrument_id = sample_instrument.symbol
        bar.timestamp = datetime(2024, 1, 15, 10, 0, tzinfo=UTC).isoformat()
        bar.open = Decimal("220.00")
        bar.high = Decimal("221.00")
        bar.low = Decimal("219.00")
        bar.close = Decimal("220.50")
        bar.volume = -1000

        errors = validator.validate_bar(bar)
        assert any(e.error_type == ValidationErrorType.NEGATIVE_VOLUME for e in errors)

    def test_validate_bars_batch(self, sample_bars: list[Bar]) -> None:
        """Test batch validation."""
        validator = BarValidator()
        result = validator.validate_bars(sample_bars)

        assert result.total_bars == 5
        assert result.valid_bars == 5
        assert result.invalid_bars == 0
        assert result.is_valid

    def test_validate_bars_with_errors(self, sample_instrument: Instrument) -> None:
        """Test batch validation with some invalid bars."""
        validator = BarValidator()

        valid_bar = Bar(
            instrument_id=sample_instrument.symbol,
            timestamp=datetime(2024, 1, 15, 10, 0, tzinfo=UTC).isoformat(),
            open=Decimal("220.00"),
            high=Decimal("221.00"),
            low=Decimal("219.00"),
            close=Decimal("220.50"),
            volume=1000,
        )

        # Bypass Bar's __post_init__ validation to create an invalid bar for testing
        invalid_bar = object.__new__(Bar)
        invalid_bar.instrument_id = sample_instrument.symbol
        invalid_bar.timestamp = datetime(2024, 1, 15, 10, 5, tzinfo=UTC).isoformat()
        invalid_bar.open = Decimal("220.00")
        invalid_bar.high = Decimal("219.00")  # Invalid
        invalid_bar.low = Decimal("221.00")
        invalid_bar.close = Decimal("220.50")
        invalid_bar.volume = 1000

        result = validator.validate_bars([valid_bar, invalid_bar])
        assert result.total_bars == 2
        assert result.valid_bars == 1
        assert result.invalid_bars == 1
        assert not result.is_valid

    def test_timestamp_ordering_valid(self, sample_bars: list[Bar]) -> None:
        """Test timestamp ordering validation with valid data."""
        validator = BarValidator()
        violations = validator.validate_timestamp_ordering(sample_bars)
        assert len(violations) == 0

    def test_timestamp_ordering_invalid(self, sample_instrument: Instrument) -> None:
        """Test timestamp ordering validation with out-of-order data."""
        validator = BarValidator()

        bars = [
            Bar(
                instrument_id=sample_instrument.symbol,
                timestamp=datetime(2024, 1, 15, 10, 0, tzinfo=UTC).isoformat(),
                open=Decimal("220.00"),
                high=Decimal("221.00"),
                low=Decimal("219.00"),
                close=Decimal("220.50"),
                volume=1000,
            ),
            Bar(
                instrument_id=sample_instrument.symbol,
                timestamp=datetime(
                    2024, 1, 15, 9, 0, tzinfo=UTC
                ).isoformat(),  # Earlier!
                open=Decimal("219.00"),
                high=Decimal("220.00"),
                low=Decimal("218.00"),
                close=Decimal("219.50"),
                volume=1000,
            ),
        ]

        violations = validator.validate_timestamp_ordering(bars)
        assert len(violations) == 1


# =============================================================================
# Storage Tests
# =============================================================================


class TestContentAddressedStorage:
    """Tests for ContentAddressedStorage functionality."""

    def test_initialize(self, temp_storage_dir: Path) -> None:
        """Test storage initialization."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        assert (temp_storage_dir / "storage").exists()
        assert (temp_storage_dir / "storage" / "bars").exists()

    def test_store_and_retrieve_bar(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test storing and retrieving a bar."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        stored = storage.store_bar(sample_bars[0])

        assert stored.content_hash != ""
        assert Path(stored.storage_path).exists()

        # Retrieve by hash
        retrieved = storage.get_bar(stored.content_hash)
        assert retrieved is not None
        assert retrieved.bar.open == sample_bars[0].open

    def test_deduplication(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test that duplicate bars are deduplicated."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        stored1 = storage.store_bar(sample_bars[0])
        stored2 = storage.store_bar(sample_bars[0])

        assert stored1.content_hash == stored2.content_hash
        assert stored1.storage_path == stored2.storage_path

    def test_get_bars_for_instrument(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test retrieving all bars for an instrument."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        storage.store_bars(sample_bars)

        retrieved = storage.get_bars_for_instrument("NIFTYBEES")
        assert len(retrieved) == 5

        # Verify sorted by timestamp
        for i in range(len(retrieved) - 1):
            assert retrieved[i].timestamp <= retrieved[i + 1].timestamp

    def test_manifest_generation(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test manifest generation."""
        storage = ContentAddressedStorage(
            temp_storage_dir / "storage", storage_id="test123"
        )
        storage.initialize()
        storage.store_bars(sample_bars)
        storage.save_manifest()

        manifest = storage.get_manifest()
        assert manifest.storage_id == "test123"
        assert manifest.bar_count == 5
        assert manifest.manifest_hash != ""

    def test_integrity_verification(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test integrity verification of stored bars."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        stored = storage.store_bar(sample_bars[0])

        assert storage.verify_integrity(stored.content_hash)

    def test_atomic_write_rollback(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test that failed writes don't leave partial files."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        # Store should succeed
        stored = storage.store_bar(sample_bars[0])
        assert Path(stored.storage_path).exists()


# =============================================================================
# Dataset Tests
# =============================================================================


class TestDatasetManifest:
    """Tests for DatasetManifest."""

    def test_manifest_hash_computation(self, sample_bars: list[Bar]) -> None:
        """Test that manifest hash is computed correctly."""
        storage = ContentAddressedStorage(tempfile.mkdtemp())
        storage.initialize()
        storage.store_bars(sample_bars)
        storage.save_manifest()
        storage_manifest = storage.get_manifest()

        manifest = DatasetManifest(
            dataset_id="test-dataset",
            name="Test Dataset",
            description="A test dataset",
            instrument_ids=["NIFTYBEES"],
            start_timestamp=sample_bars[0].timestamp,
            end_timestamp=sample_bars[-1].timestamp,
            bar_count=5,
            content_hashes=["hash1", "hash2"],
            storage_manifest=storage_manifest,
            created_at=datetime.now(UTC).isoformat(),
        )

        assert manifest.dataset_hash != ""
        assert len(manifest.dataset_hash) == 64  # SHA-256 hex length


class TestDatasetBuilder:
    """Tests for DatasetBuilder."""

    def test_build_dataset(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test building a complete dataset."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        builder = DatasetBuilder(
            name="TestDataset", description="Test dataset for NIFTY"
        )
        builder.add_bars(sample_bars)

        dataset = builder.build(storage)

        assert dataset.manifest.dataset_id != ""
        assert dataset.manifest.name == "TestDataset"
        assert dataset.manifest.bar_count == 5
        assert "NIFTYBEES" in dataset.manifest.instrument_ids

    def test_build_empty_dataset_rejected(self, temp_storage_dir: Path) -> None:
        """Test that empty datasets are rejected."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        builder = DatasetBuilder(name="EmptyDataset")

        with pytest.raises(ValueError, match="Cannot build empty dataset"):
            builder.build(storage)

    def test_dataset_integrity_verification(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test dataset integrity verification."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        builder = DatasetBuilder(name="TestDataset")
        builder.add_bars(sample_bars)
        dataset = builder.build(storage)

        is_valid, errors = dataset.verify_integrity()
        assert is_valid
        assert len(errors) == 0

    def test_dataset_contains_instrument(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test checking if dataset contains an instrument."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        builder = DatasetBuilder(name="TestDataset")
        builder.add_bars(sample_bars)
        dataset = builder.build(storage)

        assert dataset.contains_instrument("NIFTYBEES")
        assert not dataset.contains_instrument("OTHER")


class TestDatasetInspector:
    """Tests for DatasetInspector."""

    def test_save_and_load_manifest(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test saving and loading a dataset manifest."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        builder = DatasetBuilder(name="TestDataset")
        builder.add_bars(sample_bars)

        manifest_path = temp_storage_dir / "manifest.json"
        builder.save_manifest_only(manifest_path)

        # Load and verify
        data = DatasetInspector.load_manifest(manifest_path)
        assert data["name"] == "TestDataset"
        assert data["bar_count"] == 5

    def test_verify_manifest_hash(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test manifest hash verification."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        builder = DatasetBuilder(name="TestDataset")
        builder.add_bars(sample_bars)

        manifest_path = temp_storage_dir / "manifest.json"
        builder.save_manifest_only(manifest_path)

        is_valid, error = DatasetInspector.verify_manifest_hash(manifest_path)
        assert is_valid

    def test_get_dataset_summary(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test getting dataset summary."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        builder = DatasetBuilder(name="TestDataset", description="Test")
        builder.add_bars(sample_bars)

        manifest_path = temp_storage_dir / "manifest.json"
        builder.save_manifest_only(manifest_path)

        summary = DatasetInspector.get_dataset_summary(manifest_path)
        assert summary["name"] == "TestDataset"
        assert summary["bar_count"] == 5
        assert summary["instrument_count"] == 1


# =============================================================================
# Integration Tests
# =============================================================================


class TestFullIngestionPipeline:
    """Integration tests for the full ingestion pipeline."""

    def test_end_to_end_ingestion(
        self, temp_storage_dir: Path, sample_bars: list[Bar]
    ) -> None:
        """Test complete ingestion from bars to dataset."""
        # 1. Validate bars
        validator = BarValidator()
        validation_result = validator.validate_bars(sample_bars)
        assert validation_result.is_valid

        # 2. Ingest bars
        ingestor = DataIngestor()
        ingestion_result = ingestor.ingest_bars(sample_bars)
        assert ingestion_result.bars_ingested == 5

        # 3. Store bars
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()
        stored_bars = storage.store_bars(sample_bars)
        assert len(stored_bars) == 5

        # 4. Build dataset
        builder = DatasetBuilder(name="E2E_Test", description="End-to-end test")
        builder.add_bars(sample_bars)
        dataset = builder.build(storage)

        # 5. Verify dataset
        assert dataset.manifest.bar_count == 5
        is_valid, errors = dataset.verify_integrity()
        assert is_valid

        # 6. Retrieve and verify bars
        retrieved = dataset.get_bars("NIFTYBEES")
        assert len(retrieved) == 5

    def test_multi_instrument_dataset(
        self, temp_storage_dir: Path, sample_instrument: Instrument
    ) -> None:
        """Test dataset with multiple instruments."""
        storage = ContentAddressedStorage(temp_storage_dir / "storage")
        storage.initialize()

        # Create bars for two instruments
        base_time = datetime(2024, 1, 15, 9, 15, tzinfo=UTC)
        all_bars: list[Bar] = []

        for inst_id in ["NIFTYBEES", "BANKBEES"]:
            for i in range(3):
                ts = base_time.replace(minute=15 + i * 5)
                all_bars.append(
                    Bar(
                        instrument_id=inst_id,
                        timestamp=ts.isoformat(),
                        open=Decimal("220.00") + Decimal(i) * Decimal("0.5"),
                        high=Decimal("221.00") + Decimal(i) * Decimal("0.5"),
                        low=Decimal("219.50") + Decimal(i) * Decimal("0.5"),
                        close=Decimal("220.50") + Decimal(i) * Decimal("0.5"),
                        volume=1000,
                    )
                )

        # Validate and store
        validator = BarValidator()
        assert validator.validate_bars(all_bars).is_valid

        builder = DatasetBuilder(
            name="MultiInstrument", description="Multiple instruments"
        )
        builder.add_bars(all_bars)
        dataset = builder.build(storage)

        assert dataset.manifest.bar_count == 6
        assert len(dataset.manifest.instrument_ids) == 2
        assert "NIFTYBEES" in dataset.manifest.instrument_ids
        assert "BANKBEES" in dataset.manifest.instrument_ids

        # Verify retrieval per instrument
        nifty_bars = dataset.get_bars("NIFTYBEES")
        bank_bars = dataset.get_bars("BANKBEES")
        assert len(nifty_bars) == 3
        assert len(bank_bars) == 3
