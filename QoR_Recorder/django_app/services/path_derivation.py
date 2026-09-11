"""Canonical path-derived metadata for new QoR imports."""
from __future__ import annotations

import re
from dataclasses import dataclass


_REGR_SEGMENT = re.compile(r"^regr_[A-Za-z0-9][A-Za-z0-9._-]*$", re.IGNORECASE)
_SYN_REGR_SEGMENT = re.compile(r"^syn_regr_[A-Za-z0-9][A-Za-z0-9._-]*$", re.IGNORECASE)
_QUARTER_WEEK_SEGMENT = re.compile(r"^\d{4}Q[1-4]_w\d+$", re.IGNORECASE)
_LEGACY_RELEASE_SEGMENT = re.compile(r"^v\d+(?:[._-]\d+)*$", re.IGNORECASE)
_CONTROLLED_FALLBACK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def _is_version_segment(value: str) -> bool:
    return bool(
        _SYN_REGR_SEGMENT.fullmatch(value)
        or _REGR_SEGMENT.fullmatch(value)
        or _QUARTER_WEEK_SEGMENT.fullmatch(value)
        or _LEGACY_RELEASE_SEGMENT.fullmatch(value)
    )


@dataclass(frozen=True)
class PathDerivationError(ValueError):
    code: str
    message: str
    full_dir: object = None

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "field": "full_dir", "value": self.full_dir}


def normalize_full_dir(full_dir: str) -> str:
    """Return a platform-neutral path without touching the filesystem."""
    if not isinstance(full_dir, str) or not full_dir.strip():
        raise PathDerivationError("missing_full_dir", "full_dir is required", full_dir)
    value = re.sub(r"[\\/]+", "/", full_dir.strip())
    if value != "/" and not re.fullmatch(r"[A-Za-z]:/", value):
        value = value.rstrip("/")
    segments = value.split("/")
    collapsed: list[str] = []
    for segment in segments:
        if segment == ".":
            continue
        if segment == "..":
            raise PathDerivationError(
                "unsafe_full_dir", "full_dir must not contain parent traversal", full_dir
            )
        collapsed.append(segment)
    normalized = "/".join(collapsed)
    if not normalized:
        raise PathDerivationError("invalid_full_dir", "full_dir has no valid path segments", full_dir)
    return normalized


def derive_version(full_dir: str, fallback: str | None = None) -> str:
    """Derive version only from full_dir.

    Supported version segments are ``syn_regr_*``, ``regr_*``, release-train
    names such as ``2026Q3_w3``, and legacy release names such as ``v1``/``v1.2``.
    If ``main`` is present, the nearest valid version segment directly before it
    wins. Otherwise the last valid version segment is used.

    ``fallback`` is only used by controlled import surfaces when the path has
    no version segment. It is deliberately validated and opt-in so callers
    cannot silently recreate the historical unconditional ``v1`` fallback.
    """
    normalized = normalize_full_dir(full_dir)
    segments = [segment for segment in normalized.split("/") if segment]
    candidates = [
        index for index, segment in enumerate(segments)
        if _is_version_segment(segment)
    ]
    for index, segment in enumerate(segments):
        if (
            segment.lower() == "main"
            and index > 0
            and _is_version_segment(segments[index - 1])
        ):
            return segments[index - 1]
    if candidates:
        return segments[candidates[-1]]
    if fallback is not None:
        fallback_value = str(fallback).strip()
        if _CONTROLLED_FALLBACK.fullmatch(fallback_value):
            return fallback_value
        raise PathDerivationError(
            "invalid_version_fallback",
            "upload version fallback must contain only letters, numbers, '.', '_' or '-'",
            full_dir,
        )
    raise PathDerivationError(
        "version_not_in_path",
        "full_dir must contain a valid syn_regr_*, regr_*, YYYYQn_wN, or vN version segment",
        full_dir,
    )


def derive_path_metadata(full_dir: str) -> dict[str, str]:
    normalized = normalize_full_dir(full_dir)
    return {
        "full_dir": normalized,
        "version": derive_version(normalized),
        "tag": normalized.rsplit("/", 1)[-1],
    }
