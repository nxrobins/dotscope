"""Eval harness: autoresearch fitness for dotscope candidates."""

from .harness import evaluate_gates, compute_primary, compute_secondary, fitness
from .corpus import generate_corpus, load_corpus, save_corpus
from .replay import replay_corpus
from .compare import compare_runs

__all__ = [
    "evaluate_gates",
    "compute_primary",
    "compute_secondary",
    "fitness",
    "generate_corpus",
    "load_corpus",
    "save_corpus",
    "replay_corpus",
    "compare_runs",
]
