"""Backward-compatibility facade for dotscope.workflows.absorber."""

from ._compat import install_compat_shim

install_compat_shim(__name__, ".workflows.absorber")
