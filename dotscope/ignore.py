"""Backward-compatibility facade for dotscope.engine.ignore."""

from ._compat import install_compat_shim

install_compat_shim(__name__, ".engine.ignore")
