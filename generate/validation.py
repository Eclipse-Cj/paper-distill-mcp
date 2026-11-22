"""Checks for values that end up in file paths.

Tool arguments come from an AI client. They can be chosen by someone else, for
example through prompt injection, so no argument is used in a path before it has
passed one of the checks in this module.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
# Characters that are not allowed in file names on at least one supported platform.
_ILLEGAL_CHARS_RE = re.compile(r'[<>:"|?*\x00-\x1f]')
_SEPARATORS_RE = re.compile(r"[/\\]")


def validate_date(value: object) -> str:
    """Return ``value`` if it is a calendar date written as YYYY-MM-DD.

    Raises:
        ValueError: for anything else, including values that contain a path
            separator or "..".
    """
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ValueError(f"date must be in YYYY-MM-DD format, got {value!r}")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"date is not a real calendar date: {value!r}") from None
    return value


def safe_filename(value: object, default: str) -> str:
    """Turn a label into one file name with no path separators."""
    text = value if isinstance(value, str) else ""
    text = _SEPARATORS_RE.sub("", _ILLEGAL_CHARS_RE.sub("", text)).strip()
    return text if text.strip(".") else default


def safe_relative_dir(value: object, default: str) -> Path:
    """Turn a folder label such as "nlp/agents" into a relative path.

    Separators keep their meaning, so nested folders still work. Every segment
    is cleaned, and empty, "." and ".." segments are dropped, so the result can
    never point above the folder it is joined to.
    """
    text = value if isinstance(value, str) else ""
    segments = []
    for raw in _SEPARATORS_RE.split(text):
        segment = _ILLEGAL_CHARS_RE.sub("", raw).strip().strip(".").strip()
        if segment:
            segments.append(segment)
    return Path(*segments) if segments else Path(default)


def ensure_within(base: Path, target: Path) -> Path:
    """Return ``target`` if it lies inside ``base`` once both are resolved.

    Raises:
        ValueError: if ``target`` would be outside ``base``.
    """
    if not target.resolve().is_relative_to(base.resolve()):
        raise ValueError(f"refusing to write outside {base}: {target}")
    return target
