"""Canonical path-derived metadata for new QoR imports."""
from __future__ import annotations

import re
from dataclasses import dataclass


_REGR_SEGMENT = re.compile(r"^regr_[A-Za-z0-9][A-Za-z0-9._-]*$", re.IGNORECASE)


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


def derive_version(full_dir: str) -> str:
    """Derive version only from full_dir.

    If ``main`` is present, the nearest valid ``regr_*`` segment directly before
    it wins. Otherwise the last valid ``regr_*`` segment is used.
    """
    normalized = normalize_full_dir(full_dir)
    segments = [segment for segment in normalized.split("/") if segment]
    candidates = [index for index, segment in enumerate(segments) if _REGR_SEGMENT.fullmatch(segment)]
    for index, segment in enumerate(segments):
        if segment.lower() == "main" and index > 0 and _REGR_SEGMENT.fullmatch(segments[index - 1]):
            return segments[index - 1]
    if candidates:
        return segments[candidates[-1]]
    raise PathDerivationError(
        "version_not_in_path",
        "full_dir must contain a valid regr_* segment; new imports have no version fallback",
        full_dir,
    )


def derive_path_metadata(full_dir: str) -> dict[str, str]:
    normalized = normalize_full_dir(full_dir)
    return {
        "full_dir": normalized,
        "version": derive_version(normalized),
        "tag": normalized.rsplit("/", 1)[-1],
    }
