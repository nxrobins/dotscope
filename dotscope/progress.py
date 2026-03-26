"""Streaming progress for long-running pipeline steps.

Emits terse status lines to stderr as each step begins and completes.
The developer watches the tool think instead of staring at silence.
"""

import sys
import time


class ProgressEmitter:
    """Emit streaming progress for pipeline steps."""

    def __init__(self, quiet: bool = False, stream=None):
        self._quiet = quiet
        self._stream = stream or sys.stderr
        self._start_time = 0.0

    def start(self, action: str) -> None:
        """Print action with trailing ... (no newline)."""
        if self._quiet:
            return
        self._stream.write(f"dotscope: {action}...")
        self._stream.flush()
        self._start_time = time.perf_counter()

    def finish(self, result: str) -> None:
        """Complete the current line with the result."""
        if self._quiet:
            return
        elapsed = time.perf_counter() - self._start_time
        pad = " " * max(1, 45 - len(result))
        if elapsed > 1.0:
            self._stream.write(f"{pad}{result} ({elapsed:.1f}s)\n")
        else:
            self._stream.write(f"{pad}{result}\n")
        self._stream.flush()

    def skip(self, action: str, reason: str) -> None:
        """Show a skipped step."""
        if self._quiet:
            return
        self._stream.write(f"dotscope: {action}... skipped ({reason})\n")
        self._stream.flush()
