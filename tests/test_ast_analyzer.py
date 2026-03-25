"""Tests for AST-powered code analysis."""

import os
import pytest
from dotscope.ast_analyzer import analyze_file, resolve_python_import
from dotscope.models import ResolvedImport


class TestPythonAST:
    def test_extracts_imports(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("import os\nfrom pathlib import Path\nfrom . import utils\n")

        api = analyze_file(str(f), "python")
        assert api is not None
        assert len(api.imports) == 3
        raws = [i.raw for i in api.imports]
        assert "os" in raws
        assert "pathlib" in raws
        assert any(i.is_relative for i in api.imports)

    def test_extracts_star_import(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("from os.path import *\n")

        api = analyze_file(str(f), "python")
        assert any(i.is_star for i in api.imports)

    def test_extracts_functions(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text(
            "def public_fn(x: int, y: str = 'default') -> bool:\n"
            "    pass\n\n"
            "def _private_fn():\n"
            "    pass\n"
        )

        api = analyze_file(str(f), "python")
        assert len(api.functions) == 2
        pub = next(fn for fn in api.functions if fn.name == "public_fn")
        assert pub.is_public
        assert "x: int" in pub.params
        assert pub.return_type == "bool"

        priv = next(fn for fn in api.functions if fn.name == "_private_fn")
        assert not priv.is_public

    def test_extracts_classes(self, tmp_path):
        f = tmp_path / "models.py"
        f.write_text(
            "from abc import ABC\n\n"
            "class BaseModel(ABC):\n"
            "    def save(self):\n"
            "        pass\n\n"
            "class User(BaseModel):\n"
            "    def __init__(self, name):\n"
            "        self.name = name\n"
            "    def deactivate(self):\n"
            "        pass\n"
        )

        api = analyze_file(str(f), "python")
        assert len(api.classes) == 2
        user = next(c for c in api.classes if c.name == "User")
        assert "BaseModel" in user.bases
        assert "deactivate" in user.methods

    def test_extracts_decorators(self, tmp_path):
        f = tmp_path / "routes.py"
        f.write_text(
            "from dataclasses import dataclass\n\n"
            "@dataclass\n"
            "class Config:\n"
            "    debug: bool = False\n"
        )

        api = analyze_file(str(f), "python")
        cfg = next(c for c in api.classes if c.name == "Config")
        assert "dataclass" in cfg.decorators

    def test_detects_all_list(self, tmp_path):
        f = tmp_path / "__init__.py"
        f.write_text("__all__ = ['Foo', 'Bar']\nclass Foo: pass\nclass Bar: pass\n")

        api = analyze_file(str(f), "python")
        assert api.all_list == ["Foo", "Bar"]
        assert api.public_api == ["Foo", "Bar"]

    def test_detects_entry_point(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("def run(): pass\nif __name__ == '__main__':\n    run()\n")

        api = analyze_file(str(f), "python")
        assert api.is_entry_point

    def test_extracts_docstring(self, tmp_path):
        f = tmp_path / "module.py"
        f.write_text('"""This module does stuff."""\ndef foo(): pass\n')

        api = analyze_file(str(f), "python")
        assert api.docstring == "This module does stuff."

    def test_syntax_error_returns_none(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n")

        api = analyze_file(str(f), "python")
        assert api is None

    def test_conditional_import(self, tmp_path):
        f = tmp_path / "compat.py"
        f.write_text("try:\n    import ujson as json\nexcept ImportError:\n    import json\n")

        api = analyze_file(str(f), "python")
        conditional = [i for i in api.imports if i.is_conditional]
        assert len(conditional) >= 1


class TestRelativeImportResolution:
    def test_resolves_relative_import(self, tmp_path):
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "utils.py").write_text("")

        imp = ResolvedImport(raw=".utils", is_relative=True, names=["helper"])
        resolved = resolve_python_import(imp, str(pkg / "main.py"), str(tmp_path))
        assert resolved == "pkg/utils.py"

    def test_resolves_parent_relative(self, tmp_path):
        (tmp_path / "sibling.py").write_text("")
        sub = tmp_path / "pkg"
        sub.mkdir()

        imp = ResolvedImport(raw="..sibling", is_relative=True, names=["x"])
        resolved = resolve_python_import(imp, str(sub / "main.py"), str(tmp_path))
        assert resolved == "sibling.py"


class TestJSAnalysis:
    def test_extracts_js_imports(self, tmp_path):
        f = tmp_path / "app.js"
        f.write_text(
            "import React from 'react';\n"
            "import { useState } from 'react';\n"
            "import * as utils from './utils';\n"
            "const lazy = import('./lazy');\n"
        )

        api = analyze_file(str(f), "javascript")
        assert api is not None
        assert len(api.imports) == 4
        star = [i for i in api.imports if i.is_star]
        assert len(star) == 1

    def test_extracts_exports(self, tmp_path):
        f = tmp_path / "lib.js"
        f.write_text(
            "export function helper() {}\n"
            "export class Service {}\n"
            "export const VERSION = '1.0';\n"
        )

        api = analyze_file(str(f), "javascript")
        assert len(api.exports) == 3
        names = [e.name for e in api.exports]
        assert "helper" in names
        assert "Service" in names
