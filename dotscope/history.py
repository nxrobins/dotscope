"""Backward-compatibility stub. Moved to dotscope.passes.history_miner."""
from .passes.history_miner import *  # noqa: F401,F403
from .models.history import (  # noqa: F401
    FileChange, CommitInfo, FileHistory,
    ChangeCoupling, ImplicitContract, HistoryAnalysis,
)
