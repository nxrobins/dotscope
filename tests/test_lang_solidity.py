"""Tests for tree-sitter Solidity analyzer."""

import os
import pytest
import tempfile

from dotscope.passes.lang._treesitter import AVAILABLE
from dotscope.models.core import ResolvedImport


pytestmark = pytest.mark.skipif(not AVAILABLE, reason="tree-sitter not installed")


def _has_solidity():
    try:
        import tree_sitter_solidity  # noqa: F401
        return True
    except ImportError:
        return False


skip_no_solidity = pytest.mark.skipif(
    not _has_solidity(), reason="tree-sitter-solidity not installed"
)


@skip_no_solidity
class TestSolidityAnalyzer:

    def _analyze(self, source):
        from dotscope.passes.lang.solidity import SolidityAnalyzer
        analyzer = SolidityAnalyzer()
        with tempfile.NamedTemporaryFile(suffix=".sol", mode="w", delete=False, encoding="utf-8") as f:
            f.write(source)
            f.flush()
            result = analyzer.analyze(f.name, source)
        os.unlink(f.name)
        return result

    def test_basic_contract(self):
        result = self._analyze("""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract SimpleStorage {
    uint256 private storedData;

    function set(uint256 x) public {
        storedData = x;
    }

    function get() public view returns (uint256) {
        return storedData;
    }
}
""")
        assert result is not None
        assert result.language == "solidity"
        assert len(result.classes) == 1
        assert result.classes[0].name == "SimpleStorage"
        assert "set" in result.classes[0].methods
        assert "get" in result.classes[0].methods

    def test_imports(self):
        result = self._analyze("""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "./Math.sol";
import "../interfaces/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";

contract Token {}
""")
        assert result is not None
        assert len(result.imports) == 3

        assert result.imports[0].raw == "./Math.sol"
        assert result.imports[0].is_relative
        assert result.imports[0].module == "Math"

        assert result.imports[1].raw == "../interfaces/IERC20.sol"
        assert result.imports[1].is_relative

        assert result.imports[2].raw == "@openzeppelin/contracts/token/ERC20/ERC20.sol"
        assert not result.imports[2].is_relative
        assert result.imports[2].module == "ERC20"

    def test_inheritance(self):
        result = self._analyze("""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Ownable {
    address public owner;
}

contract Pausable is Ownable {
    bool public paused;
}

contract Token is Pausable, Ownable {
    string public name;
}
""")
        assert result is not None
        contracts = {c.name: c for c in result.classes}

        assert "Ownable" in contracts
        assert contracts["Ownable"].bases == []

        assert "Pausable" in contracts
        assert "Ownable" in contracts["Pausable"].bases

        assert "Token" in contracts
        assert "Pausable" in contracts["Token"].bases
        assert "Ownable" in contracts["Token"].bases

    def test_interface(self):
        result = self._analyze("""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface IERC20 {
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
}
""")
        assert result is not None
        assert len(result.classes) == 1
        iface = result.classes[0]
        assert iface.name == "IERC20"
        assert iface.is_abstract
        assert "totalSupply" in iface.methods
        assert "balanceOf" in iface.methods
        assert "transfer" in iface.methods

    def test_library(self):
        result = self._analyze("""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

library SafeMath {
    function add(uint256 a, uint256 b) internal pure returns (uint256) {
        return a + b;
    }
}
""")
        assert result is not None
        assert len(result.classes) == 1
        lib = result.classes[0]
        assert lib.name == "SafeMath"
        assert "add" in lib.methods

    def test_function_visibility(self):
        result = self._analyze("""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Vault {
    function deposit() public payable {}
    function withdraw() external {}
    function _validate() internal view {}
    function __helper() private pure {}
}
""")
        assert result is not None
        fns = {f.name: f for f in result.functions}

        if "deposit" in fns:
            assert fns["deposit"].is_public
        if "withdraw" in fns:
            assert fns["withdraw"].is_public
        if "_validate" in fns:
            assert not fns["_validate"].is_public
        if "__helper" in fns:
            assert not fns["__helper"].is_public

    def test_modifier_definition(self):
        result = self._analyze("""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Ownable {
    modifier onlyOwner() {
        require(msg.sender == owner);
        _;
    }
}
""")
        assert result is not None
        modifier_fns = [f for f in result.functions if "modifier" in f.decorators]
        assert len(modifier_fns) >= 1
        assert any(f.name == "onlyOwner" for f in modifier_fns)


@skip_no_solidity
class TestSolidityImportResolution:

    def test_relative_import(self, tmp_path):
        from dotscope.passes.lang.solidity import resolve_solidity_import

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Token.sol").write_text("contract Token {}", encoding="utf-8")
        (tmp_path / "src" / "Math.sol").write_text("library Math {}", encoding="utf-8")

        imp = ResolvedImport(raw="./Math.sol", module="Math", is_relative=True)
        result = resolve_solidity_import(
            imp, str(tmp_path / "src" / "Token.sol"), str(tmp_path)
        )
        assert result is not None
        assert "Math.sol" in result

    def test_bare_import_resolves_locally(self, tmp_path):
        from dotscope.passes.lang.solidity import resolve_solidity_import

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Token.sol").write_text("contract Token {}", encoding="utf-8")
        (tmp_path / "src" / "Math.sol").write_text("library Math {}", encoding="utf-8")

        imp = ResolvedImport(raw="Math.sol", module="Math", is_relative=False)
        result = resolve_solidity_import(
            imp, str(tmp_path / "src" / "Token.sol"), str(tmp_path)
        )
        assert result is not None
        assert "Math.sol" in result

    def test_external_import_returns_none(self, tmp_path):
        from dotscope.passes.lang.solidity import resolve_solidity_import

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Token.sol").write_text("contract Token {}", encoding="utf-8")

        imp = ResolvedImport(
            raw="@openzeppelin/contracts/token/ERC20/ERC20.sol",
            module="ERC20",
            is_relative=False,
        )
        result = resolve_solidity_import(
            imp, str(tmp_path / "src" / "Token.sol"), str(tmp_path)
        )
        assert result is None

    def test_remappings_resolution(self, tmp_path):
        from dotscope.passes.lang.solidity import resolve_solidity_import, _remappings_cache

        _remappings_cache.clear()

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "Token.sol").write_text("contract Token {}", encoding="utf-8")
        lib_path = tmp_path / "lib" / "openzeppelin-contracts" / "contracts" / "token" / "ERC20"
        lib_path.mkdir(parents=True)
        (lib_path / "ERC20.sol").write_text("contract ERC20 {}", encoding="utf-8")

        (tmp_path / "remappings.txt").write_text(
            "@openzeppelin/contracts/=lib/openzeppelin-contracts/contracts/\n",
            encoding="utf-8",
        )

        imp = ResolvedImport(
            raw="@openzeppelin/contracts/token/ERC20/ERC20.sol",
            module="ERC20",
            is_relative=False,
        )
        result = resolve_solidity_import(
            imp, str(tmp_path / "src" / "Token.sol"), str(tmp_path)
        )
        assert result is not None
        assert "ERC20.sol" in result

        _remappings_cache.clear()
