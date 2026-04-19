"""Backward-compatibility facade for dotscope.ux.health."""

from ._compat import install_compat_shim

install_compat_shim(__name__, ".ux.health")
