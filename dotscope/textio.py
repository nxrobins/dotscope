"""Shared text decoding for repo-authored files.

Repo files should decode best-effort so analysis keeps moving on Windows
codebases that still contain legacy-encoded files. dotscope-owned state under
.dotscope remains strict UTF-8.
"""

from __future__ import annotations

import codecs
import os
from dataclasses import dataclass
from typing import Iterable, List, Set

from .constants import SKIP_DIRS, SOURCE_EXTS


REPO_TEXT_EXTS = SOURCE_EXTS | frozenset({
    ".md", ".rst", ".txt", ".adoc",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".json", ".sh", ".bash", ".zsh", ".ps1", ".bat",
    ".sql",
})

REPO_TEXT_NAMES = frozenset({
    ".scope",
    ".scopes",
    "intent.yaml",
    "intent.yml",
    "readme",
    "readme.md",
    "readme.rst",
    "dockerfile",
    "makefile",
})

_decode_warnings: Set[str] = set()


@dataclass(frozen=True)
class DecodedText:
    text: str
    encoding: str
    used_replacement: bool = False


def decode_repo_bytes(data: bytes, source: str = "") -> DecodedText:
    """Decode repo-authored text with a deterministic fallback policy."""
    if data.startswith(codecs.BOM_UTF8):
        return DecodedText(
            text=data.decode("utf-8-sig"),
            encoding="utf-8-sig",
            used_replacement=False,
        )
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return DecodedText(
            text=data.decode("utf-32"),
            encoding="utf-32",
            used_replacement=False,
        )
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return DecodedText(
            text=data.decode("utf-16"),
            encoding="utf-16",
            used_replacement=False,
        )

    try:
        return DecodedText(
            text=data.decode("utf-8"),
            encoding="utf-8",
            used_replacement=False,
        )
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
        if source:
            _decode_warnings.add(source)
        return DecodedText(text=text, encoding="utf-8", used_replacement=True)


def read_repo_text(path: str) -> DecodedText:
    """Read a repo-authored text file with best-effort decoding."""
    with open(path, "rb") as f:
        return decode_repo_bytes(f.read(), source=path)


def consume_decode_warnings() -> List[str]:
    """Return and clear the set of lossy decode warning sources."""
    warnings = sorted(_decode_warnings)
    _decode_warnings.clear()
    return warnings


def is_dotscope_internal_path(path: str) -> bool:
    """Return True when a path lives under .dotscope machine state."""
    abs_path = os.path.abspath(path)
    return ".dotscope" in abs_path.split(os.sep)


def is_repo_text_path(path: str) -> bool:
    """Heuristic for repo-authored text worth scanning for encoding issues."""
    name = os.path.basename(path)
    lower_name = name.lower()
    if lower_name in REPO_TEXT_NAMES:
        return True
    if lower_name.startswith("readme"):
        return True
    ext = os.path.splitext(lower_name)[1]
    return ext in REPO_TEXT_EXTS


def iter_repo_text_files(root: str) -> Iterable[str]:
    """Yield repo-authored text files, excluding dotscope machine state."""
    skip_dirs = set(SKIP_DIRS)
    skip_dirs.add(".dotscope")

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            if is_repo_text_path(full_path):
                yield full_path
