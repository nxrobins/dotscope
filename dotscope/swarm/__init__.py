"""Swarm-ready primitives for parallel agent coordination.

Three read-only tools that make dotscope the sensory layer for agent swarms:
  partition_search_space — divide work into non-overlapping starting points
  resolve_trace — follow an execution path with focused context
  merge_scout_findings — cross-reference parallel findings against codebase structure
"""

from .partition import partition_search_space
from .trace import resolve_trace
from .merge import merge_scout_findings

__all__ = ["partition_search_space", "resolve_trace", "merge_scout_findings"]
