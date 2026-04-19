"""Backward-compatibility facade for dotscope.workflows.lessons."""

from ._compat import install_compat_shim

install_compat_shim(__name__, ".workflows.lessons")
