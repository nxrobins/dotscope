"""Tests for top-level compatibility shims and lazy package access."""

import importlib
import sys

import dotscope


LEGACY_SHIMS = {
    "absorber": "dotscope.workflows.absorber",
    "assertions": "dotscope.engine.assertions",
    "bench": "dotscope.ux.bench",
    "composer": "dotscope.engine.composer",
    "constants": "dotscope.engine.constants",
    "context": "dotscope.engine.context",
    "counterfactual": "dotscope.ux.counterfactual",
    "debug": "dotscope.ux.debug",
    "discovery": "dotscope.engine.discovery",
    "explain": "dotscope.ux.explain",
    "formatter": "dotscope.ux.formatter",
    "health": "dotscope.ux.health",
    "ignore": "dotscope.engine.ignore",
    "ingest": "dotscope.workflows.ingest",
    "intent": "dotscope.workflows.intent",
    "lessons": "dotscope.workflows.lessons",
    "matcher": "dotscope.engine.matcher",
    "parser": "dotscope.engine.parser",
    "refresh": "dotscope.workflows.refresh",
    "regression": "dotscope.workflows.regression",
    "resolver": "dotscope.engine.resolver",
    "runtime_overlay": "dotscope.engine.runtime_overlay",
    "scanner": "dotscope.engine.scanner",
    "textio": "dotscope.ux.textio",
    "utility": "dotscope.engine.utility",
    "visibility": "dotscope.ux.visibility",
}


class TestCompatShims:
    def test_all_legacy_shims_import(self):
        for legacy_name, target_name in LEGACY_SHIMS.items():
            compat_module = importlib.import_module(f"dotscope.{legacy_name}")
            target_module = importlib.import_module(target_name)
            assert compat_module.__doc__
            assert "Backward-compatibility facade" in compat_module.__doc__
            assert compat_module.__name__ == f"dotscope.{legacy_name}"
            assert compat_module is not target_module

    def test_package_getattr_lazily_resolves_compat_module(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "dotscope.refresh", raising=False)
        monkeypatch.delattr(dotscope, "refresh", raising=False)

        module = dotscope.refresh

        assert module.__name__ == "dotscope.refresh"
        assert sys.modules["dotscope.refresh"] is module

    def test_monkeypatch_path_resolves_refresh_shim(self, monkeypatch):
        sentinel = object()
        monkeypatch.setattr("dotscope.refresh._wait_for_repo_refresh", lambda root, timeout_seconds: sentinel)

        from dotscope.workflows.refresh import _wait_for_repo_refresh as canonical_wait
        from dotscope.refresh import _wait_for_repo_refresh

        assert _wait_for_repo_refresh("repo", 1.0) is sentinel
        assert canonical_wait("repo", 1.0) is sentinel
