"""Backward-compatibility facade for dotscope.engine.resolver."""

from ._compat import install_compat_shim

install_compat_shim(__name__, ".engine.resolver")
