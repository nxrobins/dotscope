"""Tests for the scope resolver."""

import os
import pytest
from dotscope.parser import parse_scope_file
from dotscope.resolver import resolve


class TestResolve:
    def test_basic_resolve(self, tmp_project):
        config = parse_scope_file(str(tmp_project / "auth" / ".scope"))
        result = resolve(config, follow_related=False, root=str(tmp_project))

        # Should include auth files
        basenames = [os.path.basename(f) for f in result.files]
        assert "__init__.py" in basenames
        assert "handler.py" in basenames
        assert "tokens.py" in basenames

        # Should include models/user.py
        assert any("user.py" in f for f in result.files)

        # Should NOT include fixtures (excluded)
        assert not any("users.json" in f for f in result.files)

    def test_context_included(self, tmp_project):
        config = parse_scope_file(str(tmp_project / "auth" / ".scope"))
        result = resolve(config, follow_related=False, root=str(tmp_project))

        assert "JWT tokens" in result.context
        assert result.token_estimate > 0

    def test_follow_related(self, tmp_project):
        config = parse_scope_file(str(tmp_project / "auth" / ".scope"))
        result = resolve(config, follow_related=True, root=str(tmp_project))

        # Should include payment files from related scope
        assert any("billing.py" in f for f in result.files)
        assert len(result.scope_chain) >= 2

    def test_no_related(self, tmp_project):
        config = parse_scope_file(str(tmp_project / "auth" / ".scope"))
        result = resolve(config, follow_related=False, root=str(tmp_project))

        # Should NOT include payment files
        assert not any("billing.py" in f for f in result.files)
        assert len(result.scope_chain) == 1

    def test_cycle_detection(self, tmp_path):
        """Two scopes that reference each other should not loop."""
        (tmp_path / ".git").mkdir()

        a = tmp_path / "a"
        a.mkdir()
        (a / "file.py").write_text("# A\n")
        (a / ".scope").write_text(
            "description: Module A\n"
            "includes:\n"
            "  - a/\n"
            "related:\n"
            "  - b/.scope\n"
        )

        b = tmp_path / "b"
        b.mkdir()
        (b / "file.py").write_text("# B\n")
        (b / ".scope").write_text(
            "description: Module B\n"
            "includes:\n"
            "  - b/\n"
            "related:\n"
            "  - a/.scope\n"
        )

        config = parse_scope_file(str(a / ".scope"))
        result = resolve(config, follow_related=True, root=str(tmp_path))

        # Should complete without infinite loop
        assert any("file.py" in f for f in result.files)

    def test_exclude_glob(self, tmp_path):
        (tmp_path / ".git").mkdir()
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("# app\n")
        (src / "app.generated.py").write_text("# generated\n")
        (src / ".scope").write_text(
            "description: Source\n"
            "includes:\n"
            "  - src/\n"
            "excludes:\n"
            '  - "*.generated.py"\n'
        )

        config = parse_scope_file(str(src / ".scope"))
        result = resolve(config, follow_related=False, root=str(tmp_path))

        basenames = [os.path.basename(f) for f in result.files]
        assert "app.py" in basenames
        assert "app.generated.py" not in basenames
