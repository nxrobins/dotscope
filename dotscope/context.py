"""Backward-compatibility facade for dotscope.engine.context."""

from ._compat import install_compat_shim

install_compat_shim(__name__, ".engine.context")
