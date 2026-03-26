"""Tests for canonical snippet extraction."""

import os
import tempfile

from dotscope.passes.voice import extract_canonical_snippet


class TestCanonicalSnippet:
    def test_extracts_class_not_imports(self):
        src = (
            "import os\n"
            "import sys\n"
            "\n"
            "class UserRepo:\n"
            "    def get(self, user_id: int):\n"
            "        return self.db.query(user_id)\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "repo.py")
            with open(path, "w") as f:
                f.write(src)
            snippet = extract_canonical_snippet(path, d)
            assert snippet is not None
            assert "class UserRepo" in snippet
            assert "import os" not in snippet

    def test_extracts_function_if_no_class(self):
        src = (
            "import json\n"
            "\n"
            "def process(data: dict) -> dict:\n"
            "    return {k: v for k, v in data.items()}\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "util.py")
            with open(path, "w") as f:
                f.write(src)
            snippet = extract_canonical_snippet(path, d)
            assert snippet is not None
            assert "def process" in snippet
            assert "import json" not in snippet

    def test_returns_none_for_empty_file(self):
        src = "# Just a comment\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "empty.py")
            with open(path, "w") as f:
                f.write(src)
            snippet = extract_canonical_snippet(path, d)
            assert snippet is None

    def test_truncates_long_class(self):
        lines = ["class Big:"]
        for i in range(60):
            lines.append(f"    def method_{i}(self): pass")
        src = "\n".join(lines) + "\n"

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "big.py")
            with open(path, "w") as f:
                f.write(src)
            snippet = extract_canonical_snippet(path, d, max_lines=10)
            assert snippet is not None
            assert snippet.endswith("...")
            assert snippet.count("\n") <= 10

    def test_nonexistent_file_returns_none(self):
        snippet = extract_canonical_snippet("/nonexistent/file.py", "/tmp")
        assert snippet is None
