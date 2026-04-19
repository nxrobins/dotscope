"""Backward-compatibility facade for dotscope.engine.composer."""

from ._compat import install_compat_shim

install_compat_shim(__name__, ".engine.composer")
