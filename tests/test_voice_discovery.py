"""Tests for voice discovery: maturity detection, stats, synthesis."""

from dataclasses import dataclass, field
from typing import List, Optional

from dotscope.passes.voice_discovery import (
    VoiceStats,
    detect_codebase_maturity,
    discover_voice,
    compute_enforcement,
    _detect_docstring_style,
    _synthesize_voice,
)
from dotscope.passes.voice_defaults import prescriptive_defaults


# ---------------------------------------------------------------------------
# Maturity detection
# ---------------------------------------------------------------------------

class TestMaturity:
    def test_few_files_is_new(self):
        data = {f"f{i}.py": None for i in range(5)}
        assert detect_codebase_maturity(data, None) == "new"

    def test_many_files_no_history_is_new(self):
        data = {f"f{i}.py": None for i in range(50)}
        assert detect_codebase_maturity(data, None) == "new"

    def test_many_files_with_history_is_existing(self):
        @dataclass
        class FakeHistory:
            commits_analyzed: int = 100
        data = {f"f{i}.py": None for i in range(50)}
        assert detect_codebase_maturity(data, FakeHistory()) == "existing"

    def test_override_prescriptive(self):
        data = {f"f{i}.py": None for i in range(50)}
        assert detect_codebase_maturity(data, None, "prescriptive") == "new"

    def test_override_adaptive(self):
        data = {"a.py": None}
        assert detect_codebase_maturity(data, None, "adaptive") == "existing"


# ---------------------------------------------------------------------------
# Docstring style detection
# ---------------------------------------------------------------------------

class TestDocstringStyle:
    def test_google(self):
        assert _detect_docstring_style("Args:\n    x: int") == "google"
        assert _detect_docstring_style("Returns:\n    str") == "google"

    def test_sphinx(self):
        assert _detect_docstring_style(":param x: int") == "sphinx"
        assert _detect_docstring_style(":returns: str") == "sphinx"

    def test_numpy(self):
        assert _detect_docstring_style("Parameters\n----------") == "numpy"

    def test_other(self):
        assert _detect_docstring_style("Just a description.") == "other"


# ---------------------------------------------------------------------------
# Enforcement derivation
# ---------------------------------------------------------------------------

class TestEnforcement:
    def test_strict_codebase(self):
        e = compute_enforcement({"bare_except_rate": 0.02, "type_hint_rate": 0.90})
        assert e["bare_excepts"] == "hold"
        assert e["missing_type_hints"] == "note"

    def test_moderate_codebase(self):
        e = compute_enforcement({"bare_except_rate": 0.15, "type_hint_rate": 0.60})
        assert e["bare_excepts"] == "note"
        assert e["missing_type_hints"] is False

    def test_legacy_codebase(self):
        e = compute_enforcement({"bare_except_rate": 0.50, "type_hint_rate": 0.20})
        assert e["bare_excepts"] is False
        assert e["missing_type_hints"] is False


# ---------------------------------------------------------------------------
# Voice synthesis
# ---------------------------------------------------------------------------

class TestSynthesis:
    def test_high_type_hints(self):
        stats = VoiceStats(total_functions=100, typed_functions=90)
        voice = _synthesize_voice(stats)
        assert "Strict" in voice.rules["typing"]

    def test_low_type_hints(self):
        stats = VoiceStats(total_functions=100, typed_functions=20)
        voice = _synthesize_voice(stats)
        assert "encouraged" in voice.rules["typing"]

    def test_early_returns(self):
        stats = VoiceStats(total_return_functions=100, early_return_functions=75)
        voice = _synthesize_voice(stats)
        assert "Early returns" in voice.rules["structure"]

    def test_mode_is_adaptive(self):
        voice = _synthesize_voice(VoiceStats())
        assert voice.mode == "adaptive"


# ---------------------------------------------------------------------------
# Prescriptive defaults
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_mode(self):
        d = prescriptive_defaults()
        assert d.mode == "prescriptive"

    def test_enforce_set(self):
        d = prescriptive_defaults()
        assert d.enforce["bare_excepts"] == "hold"
        assert d.enforce["missing_type_hints"] == "note"

    def test_has_rules(self):
        d = prescriptive_defaults()
        assert "typing" in d.rules
        assert "docstrings" in d.rules
