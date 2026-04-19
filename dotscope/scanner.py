"""Backward-compatibility facade for dotscope.engine.scanner."""

from ._compat import install_compat_shim

install_compat_shim(__name__, ".engine.scanner")
