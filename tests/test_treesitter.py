"""Tests for tree-sitter language analyzers."""

import os
import pytest
import tempfile

from dotscope.passes.lang import get_analyzer
from dotscope.passes.lang._treesitter import AVAILABLE
from dotscope.passes.lang.javascript import JavaScriptAnalyzer
from dotscope.passes.lang.go import GoAnalyzer, resolve_go_import
from dotscope.models.core import ResolvedImport


pytestmark = pytest.mark.skipif(not AVAILABLE, reason="tree-sitter not installed")


# ---------------------------------------------------------------------------
# JS/TS Analyzer
# ---------------------------------------------------------------------------

class TestJavaScriptAnalyzer:

    def _analyze(self, source, ext=".js"):
        analyzer = JavaScriptAnalyzer()
        with tempfile.NamedTemporaryFile(suffix=ext, mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            result = analyzer.analyze(f.name, source)
        os.unlink(f.name)
        return result

    def test_es_imports(self):
        result = self._analyze("""
import { foo, bar } from './utils';
import * as React from 'react';
import DefaultExport from '../lib';
""")
        assert result is not None
        assert len(result.imports) == 3

        # Named import
        imp = result.imports[0]
        assert imp.raw == "./utils"
        assert imp.is_relative
        assert "foo" in imp.names

        # Star import
        imp = result.imports[1]
        assert imp.is_star
        assert imp.raw == "react"
        assert not imp.is_relative

    def test_require_imports(self):
        result = self._analyze("""
const fs = require('fs');
const utils = require('./local');
""")
        assert result is not None
        assert len(result.imports) == 2
        assert result.imports[0].raw == "fs"
        assert result.imports[1].is_relative

    def test_class_extraction(self):
        result = self._analyze("""
class UserService extends BaseService {
  async getUser(id) {
    return this.db.find(id);
  }

  deleteUser(id) {
    return this.db.delete(id);
  }
}
""")
        assert result is not None
        assert len(result.classes) == 1
        cls = result.classes[0]
        assert cls.name == "UserService"
        assert "BaseService" in cls.bases
        assert "getUser" in cls.methods
        assert "deleteUser" in cls.methods
        assert cls.method_count == 2

    def test_function_extraction(self):
        result = self._analyze("""
function processData(input) {
  return input.map(x => x * 2);
}

async function fetchUser(id) {
  return await fetch('/api/users/' + id);
}
""")
        assert result is not None
        assert len(result.functions) >= 2
        names = [f.name for f in result.functions]
        assert "processData" in names
        assert "fetchUser" in names

        fetch_fn = next(f for f in result.functions if f.name == "fetchUser")
        assert fetch_fn.is_async

    def test_exports(self):
        result = self._analyze("""
export function helper() {}
export class Service {}
export default main;
""")
        assert result is not None
        export_names = [e.name for e in result.exports]
        assert "helper" in export_names
        assert "Service" in export_names

    def test_typescript_decorators(self):
        result = self._analyze("""
@Component({selector: 'app-root'})
class AppComponent extends BaseComponent {
  getData(): string {
    return '';
  }
}
""", ext=".ts")
        assert result is not None
        assert len(result.decorators_used) > 0
        assert any("Component" in d for d in result.decorators_used)

    def test_typescript_return_types(self):
        result = self._analyze("""
function getUser(id: number): Promise<User> {
  return fetch('/api');
}
""", ext=".ts")
        assert result is not None
        fn = result.functions[0]
        assert fn.return_type is not None
        assert "Promise" in fn.return_type

    def test_arrow_functions(self):
        result = self._analyze("""
const add = (a, b) => a + b;
const fetchData = async () => { return []; };
""")
        assert result is not None
        names = [f.name for f in result.functions]
        assert "add" in names
        assert "fetchData" in names

    def test_member_expression_base(self):
        result = self._analyze("""
class App extends React.Component {
  render() { return null; }
}
""")
        assert result is not None
        cls = result.classes[0]
        assert any("React.Component" in b for b in cls.bases)


# ---------------------------------------------------------------------------
# Go Analyzer
# ---------------------------------------------------------------------------

class TestGoAnalyzer:

    def _analyze(self, source):
        analyzer = GoAnalyzer()
        with tempfile.NamedTemporaryFile(suffix=".go", mode="w", delete=False) as f:
            f.write(source)
            f.flush()
            result = analyzer.analyze(f.name, source)
        os.unlink(f.name)
        return result

    def test_imports(self):
        result = self._analyze("""
package main

import (
    "fmt"
    "net/http"
    log "github.com/sirupsen/logrus"
)
""")
        assert result is not None
        assert len(result.imports) == 3
        modules = [i.module for i in result.imports]
        assert "fmt" in modules
        assert "http" in modules

    def test_struct_and_methods(self):
        result = self._analyze("""
package main

type Server struct {
    Port int
}

func (s *Server) Start() error {
    return nil
}

func (s *Server) Stop() {
}
""")
        assert result is not None
        structs = [c for c in result.classes if c.name == "Server"]
        assert len(structs) == 1
        server = structs[0]
        assert "Start" in server.methods
        assert "Stop" in server.methods
        assert server.method_count == 2

    def test_interface(self):
        result = self._analyze("""
package main

type Reader interface {
    Read(p []byte) (int, error)
}

type ReadWriter interface {
    Reader
    Write(p []byte) (int, error)
}
""")
        assert result is not None
        classes = {c.name: c for c in result.classes}
        assert "Reader" in classes
        assert "ReadWriter" in classes
        assert "Read" in classes["Reader"].methods
        assert "Reader" in classes["ReadWriter"].bases

    def test_function_extraction(self):
        result = self._analyze("""
package main

func main() {
    fmt.Println("hello")
}

func processData(input []string) ([]int, error) {
    return nil, nil
}
""")
        assert result is not None
        names = [f.name for f in result.functions]
        assert "main" in names
        assert "processData" in names

    def test_exports_by_capitalization(self):
        result = self._analyze("""
package main

type Handler struct {}
type internal struct {}
func Serve() {}
func helper() {}
""")
        assert result is not None
        export_names = [e.name for e in result.exports]
        assert "Handler" in export_names
        assert "Serve" in export_names
        assert "internal" not in export_names
        assert "helper" not in export_names

    def test_go_import_resolution(self):
        with tempfile.TemporaryDirectory() as root:
            # Create go.mod
            with open(os.path.join(root, "go.mod"), "w") as f:
                f.write("module github.com/org/repo\n\ngo 1.21\n")

            # Create a package directory
            pkg_dir = os.path.join(root, "handler")
            os.makedirs(pkg_dir)
            with open(os.path.join(pkg_dir, "handler.go"), "w") as f:
                f.write("package handler\n")

            imp = ResolvedImport(raw="github.com/org/repo/handler")
            resolved = resolve_go_import(imp, "main.go", root)
            assert resolved is not None
            assert "handler" in resolved


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:

    def test_get_analyzer_returns_callable(self):
        js = get_analyzer("javascript")
        assert js is not None
        ts = get_analyzer("typescript")
        assert ts is not None
        go = get_analyzer("go")
        assert go is not None

    def test_unknown_returns_none(self):
        assert get_analyzer("unknown") is None

    def test_rust_returns_callable(self):
        assert get_analyzer("rust") is not None

    def test_python_returns_none(self):
        """Python uses stdlib ast, not tree-sitter."""
        assert get_analyzer("python") is None


# ---------------------------------------------------------------------------
# Integration: analyze_file dispatches to tree-sitter
# ---------------------------------------------------------------------------

class TestAnalyzeFileIntegration:

    def test_js_file_uses_treesitter(self):
        """Verify analyze_file produces rich output for JS (not regex-minimal)."""
        from dotscope.passes.ast_analyzer import analyze_file

        with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
            f.write("""
class TodoService extends BaseService {
  async getTodo(id) {
    return this.db.find(id);
  }
}
export default TodoService;
""")
            f.flush()
            result = analyze_file(f.name, "javascript")
        os.unlink(f.name)

        assert result is not None
        # tree-sitter should produce base classes (regex couldn't)
        cls = result.classes[0]
        assert cls.name == "TodoService"
        assert "BaseService" in cls.bases
        assert "getTodo" in cls.methods

    def test_go_file_uses_treesitter(self):
        from dotscope.passes.ast_analyzer import analyze_file

        with tempfile.NamedTemporaryFile(suffix=".go", mode="w", delete=False) as f:
            f.write("""
package main

import "fmt"

type Greeter struct{}

func (g *Greeter) Greet(name string) {
    fmt.Println("Hello, " + name)
}
""")
            f.flush()
            result = analyze_file(f.name, "go")
        os.unlink(f.name)

        assert result is not None
        structs = [c for c in result.classes if c.name == "Greeter"]
        assert len(structs) == 1
        assert "Greet" in structs[0].methods
