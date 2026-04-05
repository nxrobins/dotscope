import os
from typing import Optional

def find_repo_root(start_dir: Optional[str] = None) -> Optional[str]:
    """Walk up from start_dir looking for .scopes, .git, or a .scope file.

    Returns the directory containing the marker, or None.
    """
    current = os.path.abspath(start_dir or os.getcwd())

    while True:
        if os.path.isfile(os.path.join(current, ".scopes")):
            return current
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        if os.path.isfile(os.path.join(current, ".scope")):
            return current

        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    return None
