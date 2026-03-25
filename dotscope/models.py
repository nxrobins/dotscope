"""Core data models for dotscope.

This file is a backward-compatibility facade. All dataclasses are now
defined in dotscope/models/ sub-modules and re-exported here.
"""

# Re-export everything so `from dotscope.models import X` still works
from .models.core import *  # noqa: F401,F403
from .models.state import *  # noqa: F401,F403
