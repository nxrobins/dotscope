"""Tests for shared constants: extensions, language map, skip dirs."""

from dotscope.constants import LANG_MAP, SKIP_DIRS, SOURCE_EXTS


class TestSourceExts:
    def test_solidity_in_source_exts(self):
        assert ".sol" in SOURCE_EXTS

    def test_common_extensions_present(self):
        for ext in (".py", ".js", ".ts", ".go", ".rs", ".java"):
            assert ext in SOURCE_EXTS

    def test_source_exts_is_frozenset(self):
        assert isinstance(SOURCE_EXTS, frozenset)


class TestLangMap:
    def test_solidity_mapped(self):
        assert LANG_MAP[".sol"] == "Solidity"

    def test_all_keys_in_source_exts(self):
        for ext in LANG_MAP:
            assert ext in SOURCE_EXTS, f"{ext} in LANG_MAP but not in SOURCE_EXTS"

    def test_common_mappings(self):
        assert LANG_MAP[".py"] == "Python"
        assert LANG_MAP[".js"] == "JavaScript"
        assert LANG_MAP[".go"] == "Go"
        assert LANG_MAP[".rs"] == "Rust"


class TestSkipDirs:
    def test_contains_common_dirs(self):
        for d in ("__pycache__", "node_modules", ".git"):
            assert d in SKIP_DIRS

    def test_contains_build_dirs(self):
        for d in ("dist", "build", "target"):
            assert d in SKIP_DIRS

    def test_skip_dirs_is_frozenset(self):
        assert isinstance(SKIP_DIRS, frozenset)
