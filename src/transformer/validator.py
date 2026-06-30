"""
Output schema validator.

Validates the projected output against the field configuration:
- Required fields are present and non-null
- Types match the declared type
- Array types contain correct element types
"""

from __future__ import annotations

import logging
from typing import Any

from transformer.models import (
    FieldConfig,
    OnMissing,
    OutputConfig,
    ValidationError,
    ValidationResult,
)

logger = logging.getLogger(__name__)

# Type checking functions
_TYPE_CHECKERS: dict[str, type | tuple] = {
    "string": str,
    "number": (int, float),
    "boolean": bool,
    "string[]": list,
    "number[]": list,
    "object": dict,
}


def _check_type(value: Any, expected_type: str) -> bool:
    """Check if a value matches the expected type."""
    if value is None:
        return True  # None is always acceptable (handled by required check)

    checker = _TYPE_CHECKERS.get(expected_type)
    if checker is None:
        return True  # Unknown type — accept anything

    if not isinstance(value, checker):
        return False

    # For array types, check element types
    if expected_type == "string[]" and isinstance(value, list):
        return all(isinstance(v, str) for v in value)
    if expected_type == "number[]" and isinstance(value, list):
        return all(isinstance(v, (int, float)) for v in value)

    return True


class Validator:
    """Validates projected output against the output config."""

    def validate(
        self,
        output: dict[str, Any],
        config: OutputConfig,
    ) -> ValidationResult:
        """
        Validate the projected output against the config.

        Returns a ValidationResult with errors and warnings.
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationError] = []

        # Skip validation of meta-fields
        meta_fields = {"overall_confidence", "provenance", "_errors"}

        for field_config in config.fields:
            path = field_config.path

            # Check if field exists
            if path not in output:
                if field_config.required and config.on_missing != OnMissing.OMIT:
                    errors.append(ValidationError(
                        field=path,
                        message=f"Required field '{path}' is missing from output",
                        severity="error",
                    ))
                continue

            value = output[path]

            # Check required fields are non-null
            if value is None and field_config.required:
                if config.on_missing == OnMissing.ERROR:
                    errors.append(ValidationError(
                        field=path,
                        message=f"Required field '{path}' is null",
                        severity="error",
                    ))
                elif config.on_missing == OnMissing.NULL:
                    warnings.append(ValidationError(
                        field=path,
                        message=f"Required field '{path}' is null (on_missing=null)",
                        severity="warning",
                    ))
                continue

            # Type check
            if value is not None and not _check_type(value, field_config.type):
                errors.append(ValidationError(
                    field=path,
                    message=(
                        f"Field '{path}' has type {type(value).__name__}, "
                        f"expected {field_config.type}"
                    ),
                    severity="error",
                ))

        # Check for unexpected fields (informational)
        config_paths = {fc.path for fc in config.fields} | meta_fields
        for key in output:
            if key not in config_paths:
                warnings.append(ValidationError(
                    field=key,
                    message=f"Unexpected field '{key}' in output",
                    severity="warning",
                ))

        is_valid = len(errors) == 0

        if not is_valid:
            logger.warning(
                "Validation failed with %d error(s): %s",
                len(errors),
                [e.message for e in errors],
            )

        return ValidationResult(
            valid=is_valid,
            errors=errors,
            warnings=warnings,
        )

    def validate_default(
        self, output: dict[str, Any]
    ) -> ValidationResult:
        """
        Validate against the default schema (no custom config).
        Checks that the output has the expected structure.
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationError] = []

        # Required top-level fields
        required_fields = {
            "candidate_id": str,
        }

        # Optional but expected fields
        expected_fields = {
            "full_name": (str, type(None)),
            "emails": list,
            "phones": list,
            "location": (dict, type(None)),
            "links": (dict, type(None)),
            "headline": (str, type(None)),
            "years_experience": (int, float, type(None)),
            "skills": list,
            "experience": list,
            "education": list,
            "provenance": list,
            "overall_confidence": (int, float),
        }

        for field, expected_type in required_fields.items():
            if field not in output:
                errors.append(ValidationError(
                    field=field,
                    message=f"Required field '{field}' is missing",
                ))
            elif not isinstance(output[field], expected_type):
                errors.append(ValidationError(
                    field=field,
                    message=f"Field '{field}' has wrong type",
                ))

        for field, expected_type in expected_fields.items():
            if field in output and not isinstance(output[field], expected_type):
                warnings.append(ValidationError(
                    field=field,
                    message=f"Field '{field}' has unexpected type {type(output[field]).__name__}",
                    severity="warning",
                ))

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
