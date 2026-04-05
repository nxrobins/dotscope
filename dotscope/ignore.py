""".dotscopeignore support — gitignore-style exclusion patterns.

Loaded once at scan start, passed through the pipeline. No per-file IO.
"""

import fnmatch
import os
from pathlib import Path
from typing import List


def load_ignore_patterns(repo_root: str) -> List[str]:
    """Load .dotscopeignore patterns. Returns empty list if no file."""
    ignore_path = os.path.join(repo_root, ".dotscopeignore")
    if not os.path.exists(ignore_path):
        return []

    patterns = []
    try:
        with open(ignore_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    except (IOError, OSError):
        return []
    return patterns


def should_skip(
    path: str,
    skip_dirs: frozenset,
    ignore_patterns: List[str],
) -> bool:
    """Check if a path should be skipped.

    Order: hardcoded skip_dirs first (O(1) lookup),
    then .dotscopeignore patterns (glob matching).
    """
    parts = Path(path).parts
    for part in parts:
        if part in skip_dirs:
            return True

    for pattern in ignore_patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        # Directory patterns: "renderer/target/" matches any file under it
        if pattern.endswith("/"):
            dir_prefix = pattern.rstrip("/")
            if path.startswith(dir_prefix + "/") or path.startswith(dir_prefix + os.sep):
                return True
            # Also match against any path component
            for part in parts:
                if fnmatch.fnmatch(part, dir_prefix):
                    return True

    return False
