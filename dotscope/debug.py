"""Backward-compatibility facade for dotscope.ux.debug."""

from ._compat import install_compat_shim

install_compat_shim(__name__, ".ux.debug")
