"""Tests for repo text decoding helpers."""

import pytest

from dotscope.intent import load_intents
from dotscope.parser import parse_scope_file
from dotscope.textio import consume_decode_warnings, decode_repo_bytes, read_repo_text


@pytest.fixture(autouse=True)
def _clear_decode_warnings():
    consume_decode_warnings()
    yield
    consume_decode_warnings()


class TestDecodeRepoBytes:
    def test_utf8_is_lossless(self):
        decoded = decode_repo_bytes("hello".encode("utf-8"), source="demo.py")

        assert decoded.text == "hello"
        assert decoded.encoding == "utf-8"
        assert decoded.used_replacement is False
        assert consume_decode_warnings() == []

    def test_utf8_bom_is_decoded(self):
        decoded = decode_repo_bytes(b"\xef\xbb\xbfhello", source="demo.py")

        assert decoded.text == "hello"
        assert decoded.encoding == "utf-8-sig"
        assert decoded.used_replacement is False

    def test_utf16_bom_is_decoded(self):
        decoded = decode_repo_bytes("hello".encode("utf-16"), source="demo.py")

        assert decoded.text == "hello"
        assert decoded.encoding == "utf-16"
        assert decoded.used_replacement is False

    def test_invalid_utf8_uses_replacement_and_records_warning(self):
        decoded = decode_repo_bytes(b"Caf\xe9", source="legacy.py")

        assert decoded.text == "Caf\ufffd"
        assert decoded.used_replacement is True
        assert consume_decode_warnings() == ["legacy.py"]


class TestReadRepoText:
    def test_load_intents_survives_non_utf8_reason(self, tmp_path):
        intent_path = tmp_path / "intent.yaml"
        intent_path.write_bytes(
            b"intents:\n"
            b"  - directive: freeze\n"
            b"    modules: [core/]\n"
            b"    reason: Caf\xe9\n"
        )

        intents = load_intents(str(tmp_path))

        assert len(intents) == 1
        assert intents[0].directive == "freeze"
        assert intents[0].modules == ["core/"]
        assert intents[0].reason == "Caf\ufffd"

    def test_read_repo_text_records_warning_for_file(self, tmp_path):
        path = tmp_path / "README.md"
        path.write_bytes(b"# Caf\xe9\n")

        decoded = read_repo_text(str(path))

        assert decoded.used_replacement is True
        assert consume_decode_warnings() == [str(path)]

    def test_internal_runtime_scope_remains_strict_utf8(self, tmp_path):
        scope_dir = tmp_path / ".dotscope" / "runtime_scopes" / "auth"
        scope_dir.mkdir(parents=True)
        scope_path = scope_dir / ".scope"
        scope_path.write_bytes(
            b"description: Caf\xe9 scope\n"
            b"includes:\n"
            b"  - auth/\n"
        )

        with pytest.raises(UnicodeDecodeError):
            parse_scope_file(str(scope_path))
