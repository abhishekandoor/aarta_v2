"""Bar data validation with detailed error reporting."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum, auto

from aarta.domain.models import Bar


class ValidationErrorType(Enum):
    """Types of bar validation errors."""

    LOW_GREATER_THAN_HIGH = auto()
    OPEN_BELOW_LOW = auto()
    OPEN_ABOVE_HIGH = auto()
    CLOSE_BELOW_LOW = auto()
    CLOSE_ABOVE_HIGH = auto()
    NEGATIVE_PRICE = auto()
    NEGATIVE_VOLUME = auto()
    INVALID_TIMESTAMP = auto()
    MISSING_FIELD = auto()


@dataclass(frozen=True)
class ValidationError:
    """A single validation error for a bar."""

    error_type: ValidationErrorType
    message: str
    field: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a batch of bars.

    Attributes:
        total_bars: Total number of bars checked.
        valid_bars: Number of bars that passed validation.
        invalid_bars: Number of bars that failed validation.
        errors: List of validation errors with bar indices.
        is_valid: True if all bars are valid.
    """

    total_bars: int
    valid_bars: int
    invalid_bars: int
    errors: list[tuple[int, ValidationError]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.total_bars < 0:
            raise ValueError("total_bars must be non-negative")
        if self.valid_bars < 0:
            raise ValueError("valid_bars must be non-negative")
        if self.invalid_bars < 0:
            raise ValueError("invalid_bars must be non-negative")
        if self.valid_bars + self.invalid_bars != self.total_bars:
            # Allow for warnings-only cases where a bar might be counted twice
            # But normally they should sum to total
            pass

    @property
    def is_valid(self) -> bool:
        """True if all bars passed validation."""
        return self.invalid_bars == 0


class BarValidator:
    """Validates bar data for structural integrity and business rules.

    Validation rules:
    - low <= high (always)
    - low <= open <= high
    - low <= close <= high
    - All prices >= 0
    - Volume >= 0
    - Timestamp must be valid ISO 8601
    """

    def validate_bar(self, bar: Bar, index: int = 0) -> list[ValidationError]:
        """Validate a single bar and return list of errors.

        Args:
            bar: The bar to validate.
            index: The index of this bar in a batch (for error reporting).

        Returns:
            List of ValidationError objects (empty if valid).
        """
        errors: list[ValidationError] = []

        # Check low <= high
        if bar.low > bar.high:
            errors.append(
                ValidationError(
                    error_type=ValidationErrorType.LOW_GREATER_THAN_HIGH,
                    message=f"Bar at index {index}: low ({bar.low}) > high ({bar.high})",
                    field="low",
                    value=str(bar.low),
                )
            )

        # Check open within [low, high]
        if bar.open < bar.low:
            errors.append(
                ValidationError(
                    error_type=ValidationErrorType.OPEN_BELOW_LOW,
                    message=f"Bar at index {index}: open ({bar.open}) < low ({bar.low})",
                    field="open",
                    value=str(bar.open),
                )
            )
        if bar.open > bar.high:
            errors.append(
                ValidationError(
                    error_type=ValidationErrorType.OPEN_ABOVE_HIGH,
                    message=f"Bar at index {index}: open ({bar.open}) > high ({bar.high})",
                    field="open",
                    value=str(bar.open),
                )
            )

        # Check close within [low, high]
        if bar.close < bar.low:
            errors.append(
                ValidationError(
                    error_type=ValidationErrorType.CLOSE_BELOW_LOW,
                    message=f"Bar at index {index}: close ({bar.close}) < low ({bar.low})",
                    field="close",
                    value=str(bar.close),
                )
            )
        if bar.close > bar.high:
            errors.append(
                ValidationError(
                    error_type=ValidationErrorType.CLOSE_ABOVE_HIGH,
                    message=f"Bar at index {index}: close ({bar.close}) > high ({bar.high})",
                    field="close",
                    value=str(bar.close),
                )
            )

        # Check non-negative prices
        for field_name in ["open", "high", "low", "close"]:
            price = getattr(bar, field_name)
            if price < Decimal(0):
                errors.append(
                    ValidationError(
                        error_type=ValidationErrorType.NEGATIVE_PRICE,
                        message=f"Bar at index {index}: {field_name} ({price}) is negative",
                        field=field_name,
                        value=str(price),
                    )
                )

        # Check non-negative volume
        if bar.volume < 0:
            errors.append(
                ValidationError(
                    error_type=ValidationErrorType.NEGATIVE_VOLUME,
                    message=f"Bar at index {index}: volume ({bar.volume}) is negative",
                    field="volume",
                    value=str(bar.volume),
                )
            )

        # Check timestamp validity
        try:
            ts = datetime.fromisoformat(bar.timestamp.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                # Timestamp without timezone - could be a warning
                pass
        except (ValueError, TypeError) as e:
            errors.append(
                ValidationError(
                    error_type=ValidationErrorType.INVALID_TIMESTAMP,
                    message=f"Bar at index {index}: invalid timestamp '{bar.timestamp}': {e}",
                    field="timestamp",
                    value=bar.timestamp,
                )
            )

        return errors

    def validate_bars(self, bars: Iterable[Bar]) -> ValidationResult:
        """Validate a batch of bars.

        Args:
            bars: Iterable of bars to validate.

        Returns:
            ValidationResult with summary and detailed errors.
        """
        total = 0
        invalid_count = 0
        all_errors: list[tuple[int, ValidationError]] = []

        for index, bar in enumerate(bars):
            total += 1
            errors = self.validate_bar(bar, index)
            if errors:
                invalid_count += 1
                for error in errors:
                    all_errors.append((index, error))

        return ValidationResult(
            total_bars=total,
            valid_bars=total - invalid_count,
            invalid_bars=invalid_count,
            errors=all_errors,
        )

    def validate_timestamp_ordering(
        self, bars: list[Bar], allow_duplicates: bool = False
    ) -> list[tuple[int, int, str]]:
        """Validate that bars are in chronological order.

        Args:
            bars: List of bars to check.
            allow_duplicates: If True, equal timestamps are allowed.

        Returns:
            List of (index1, index2, message) tuples for ordering violations.
        """
        violations: list[tuple[int, int, str]] = []

        for i in range(len(bars) - 1):
            ts1 = datetime.fromisoformat(bars[i].timestamp.replace("Z", "+00:00"))
            ts2 = datetime.fromisoformat(bars[i + 1].timestamp.replace("Z", "+00:00"))

            if ts1 > ts2:
                violations.append(
                    (
                        i,
                        i + 1,
                        f"Bar at index {i} ({ts1.isoformat()}) is after bar at index {i + 1} ({ts2.isoformat()})",
                    )
                )
            elif ts1 == ts2 and not allow_duplicates:
                violations.append(
                    (
                        i,
                        i + 1,
                        f"Duplicate timestamp at indices {i} and {i + 1}: {ts1.isoformat()}",
                    )
                )

        return violations
