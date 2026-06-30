"""
Configurable output projector.

Transforms a CanonicalProfile into the shape requested by an OutputConfig.
Supports:
- Field selection and renaming (via `path` and `from` keys)
- Path resolution: dot notation (`location.city`) and array indexing (`emails[0]`, `skills[].name`)
- Per-field normalization
- Missing value policy (null / omit / error)
- Confidence and provenance toggle
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from transformer.models import (
    CanonicalProfile,
    FieldConfig,
    OnMissing,
    OutputConfig,
)
from transformer.normalizers import (
    normalize_phone,
    normalize_skill,
)

logger = logging.getLogger(__name__)

# Regex to parse path expressions like "skills[].name", "emails[0]"
_ARRAY_INDEX_RE = re.compile(r"^(\w+)\[(\d+)\]$")
_ARRAY_ITER_RE = re.compile(r"^(\w+)\[\]\.(\w+)$")
_DOT_PATH_RE = re.compile(r"^(\w+)\.(\w+)$")


def _resolve_path(obj: Any, path: str) -> Any:
    """
    Resolve a path expression against an object.

    Supported expressions:
    - "field" — direct attribute/key
    - "field.subfield" — nested attribute
    - "field[0]" — array index
    - "field[].subfield" — map over array, extract subfield from each element
    """
    if not path:
        return None

    # Try array iteration: "skills[].name"
    iter_match = _ARRAY_ITER_RE.match(path)
    if iter_match:
        field_name, sub_field = iter_match.groups()
        array = _get_attr_or_key(obj, field_name)
        if not isinstance(array, list):
            return None
        result = []
        for item in array:
            val = _get_attr_or_key(item, sub_field)
            if val is not None:
                result.append(val)
        return result

    # Try array index: "emails[0]"
    index_match = _ARRAY_INDEX_RE.match(path)
    if index_match:
        field_name, index_str = index_match.groups()
        array = _get_attr_or_key(obj, field_name)
        if not isinstance(array, list):
            return None
        index = int(index_str)
        if 0 <= index < len(array):
            return array[index]
        return None

    # Try dot notation: "location.city"
    dot_match = _DOT_PATH_RE.match(path)
    if dot_match:
        field_name, sub_field = dot_match.groups()
        parent = _get_attr_or_key(obj, field_name)
        if parent is None:
            return None
        return _get_attr_or_key(parent, sub_field)

    # Direct field
    return _get_attr_or_key(obj, path)


def _get_attr_or_key(obj: Any, name: str) -> Any:
    """Get attribute or dict key."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _apply_normalization(value: Any, normalize_type: str) -> Any:
    """Apply per-field normalization."""
    if value is None:
        return None

    normalize_upper = normalize_type.upper()

    if normalize_upper == "E164":
        if isinstance(value, str):
            return normalize_phone(value) or value
        elif isinstance(value, list):
            return [normalize_phone(v) or v for v in value if isinstance(v, str)]

    elif normalize_upper == "CANONICAL":
        if isinstance(value, str):
            return normalize_skill(value)
        elif isinstance(value, list):
            return [normalize_skill(v) if isinstance(v, str) else v for v in value]

    elif normalize_upper == "LOWERCASE":
        if isinstance(value, str):
            return value.lower()
        elif isinstance(value, list):
            return [v.lower() if isinstance(v, str) else v for v in value]

    elif normalize_upper == "TITLECASE":
        if isinstance(value, str):
            return value.title()

    return value


def _coerce_type(value: Any, target_type: str) -> Any:
    """Coerce a value to the expected type."""
    if value is None:
        return None

    if target_type == "string":
        return str(value) if not isinstance(value, str) else value
    elif target_type == "number":
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    elif target_type == "string[]":
        if isinstance(value, list):
            return [str(v) for v in value]
        return [str(value)]
    elif target_type == "boolean":
        return bool(value)

    return value


class Projector:
    """Projects a CanonicalProfile into the configured output shape."""

    def project(
        self,
        profile: CanonicalProfile,
        config: OutputConfig,
    ) -> dict[str, Any]:
        """
        Project a canonical profile through the output config.

        Returns a dict matching the requested schema shape.
        """
        if not config.fields:
            # No field config → return full canonical as dict
            return self._full_projection(profile, config)

        result: dict[str, Any] = {}
        errors: list[str] = []

        for field_config in config.fields:
            value = self._resolve_field(profile, field_config)

            # Apply normalization if specified
            if value is not None and field_config.normalize:
                value = _apply_normalization(value, field_config.normalize)

            # Type coercion
            if value is not None:
                value = _coerce_type(value, field_config.type)

            # Handle missing values
            if value is None:
                if field_config.required and config.on_missing == OnMissing.ERROR:
                    errors.append(
                        f"Required field '{field_config.path}' is missing"
                    )
                    continue
                elif config.on_missing == OnMissing.OMIT:
                    continue
                else:  # NULL
                    result[field_config.path] = None
            else:
                result[field_config.path] = value

        # Add confidence if requested
        if config.include_confidence:
            result["overall_confidence"] = profile.overall_confidence

        # Add provenance if requested
        if config.include_provenance:
            result["provenance"] = [
                p.model_dump() for p in profile.provenance
            ]

        if errors:
            logger.warning("Projection errors: %s", errors)
            result["_errors"] = errors

        return result

    def _resolve_field(
        self,
        profile: CanonicalProfile,
        field_config: FieldConfig,
    ) -> Any:
        """Resolve a field value from the canonical profile."""
        # Use the 'from' path if specified, otherwise use 'path'
        source_path = field_config.from_path or field_config.path
        return _resolve_path(profile, source_path)

    def _full_projection(
        self,
        profile: CanonicalProfile,
        config: OutputConfig,
    ) -> dict[str, Any]:
        """
        Full projection: convert the entire canonical profile to a dict.
        Still respects confidence/provenance toggles.
        """
        data = profile.model_dump()

        # Convert skills to include proper structure
        if "skills" in data:
            for skill in data["skills"]:
                if isinstance(skill, dict) and not config.include_confidence:
                    skill.pop("confidence", None)

        if not config.include_confidence:
            data.pop("overall_confidence", None)

        if not config.include_provenance:
            data.pop("provenance", None)

        # Handle missing values
        if config.on_missing == OnMissing.OMIT:
            data = {k: v for k, v in data.items() if v is not None}

        return data
