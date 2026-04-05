"""Tests for MCP server initialization and client detection."""

import os
from unittest.mock import patch

import pytest

from dotscope.mcp import _detect_client


class TestDetectClient:
    def test_claude_desktop_via_claude_version(self):
        with patch.dict(os.environ, {"CLAUDE_VERSION": "1.0"}, clear=True):
            assert _detect_client() == "claude-desktop"

    def test_claude_desktop_via_claude_desktop_env(self):
        with patch.dict(os.environ, {"CLAUDE_DESKTOP": "1"}, clear=True):
            assert _detect_client() == "claude-desktop"

    def test_claude_code(self):
        with patch.dict(os.environ, {"CLAUDE_CODE": "1"}, clear=True):
            assert _detect_client() == "claude-code"

    def test_cursor(self):
        with patch.dict(os.environ, {"TERM_PROGRAM": "Cursor"}, clear=True):
            assert _detect_client() == "cursor"

    def test_windsurf_via_windsurf_env(self):
        with patch.dict(os.environ, {"WINDSURF": "1"}, clear=True):
            assert _detect_client() == "windsurf"

    def test_windsurf_via_codeium_env(self):
        with patch.dict(os.environ, {"CODEIUM": "1"}, clear=True):
            assert _detect_client() == "windsurf"

    def test_vscode(self):
        with patch.dict(os.environ, {"TERM_PROGRAM": "vscode"}, clear=True):
            assert _detect_client() == "vscode"

    def test_zed_via_zed_term(self):
        with patch.dict(os.environ, {"ZED_TERM": "1"}, clear=True):
            assert _detect_client() == "zed"

    def test_zed_via_term_program(self):
        with patch.dict(os.environ, {"TERM_PROGRAM": "zed"}, clear=True):
            assert _detect_client() == "zed"

    def test_jetbrains_via_jetbrains_env(self):
        with patch.dict(os.environ, {"JETBRAINS": "1"}, clear=True):
            assert _detect_client() == "jetbrains"

    def test_jetbrains_via_terminal_emulator(self):
        with patch.dict(os.environ, {"TERMINAL_EMULATOR": "JetBrains-IDEA"}, clear=True):
            assert _detect_client() == "jetbrains"

    def test_codex_cli(self):
        with patch.dict(os.environ, {"CODEX_CLI": "1"}, clear=True):
            assert _detect_client() == "codex-cli"

    def test_unknown_when_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _detect_client() == "unknown"

    def test_priority_claude_desktop_over_vscode(self):
        """Claude Desktop env vars should take precedence."""
        with patch.dict(os.environ, {"CLAUDE_VERSION": "1.0", "TERM_PROGRAM": "vscode"}, clear=True):
            assert _detect_client() == "claude-desktop"
