"""Eval harness data models."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class GateResult:
    """Result of a single hard gate check."""
    name: str
    passed: bool
    value: float
    threshold: float
    detail: str = ""


@dataclass
class EditFrontierScore:
    """Primary fitness: edit frontier quality metrics."""
    mean_recall: float = 0.0
    mean_precision: float = 0.0
    mean_f1: float = 0.0
    mean_f2: float = 0.0
    invariant_recall: float = 1.0
    test_precision: float = 1.0
    freshness_accuracy: float = 1.0

    @property
    def composite(self) -> float:
        return (
            0.50 * self.mean_f2
            + 0.25 * self.invariant_recall
            + 0.15 * self.test_precision
            + 0.10 * self.freshness_accuracy
        )


@dataclass
class DownstreamScore:
    """Secondary fitness: downstream developer outcome metrics."""
    task_success: float = 0.0
    test_pass_rate: float = 0.0
    scope_expansions: float = 1.0
    irrelevant_files: float = 1.0
    token_cost: float = 1.0
    override_rate: float = 1.0
    false_warning_rate: float = 1.0

    @property
    def composite(self) -> float:
        return (
            0.30 * self.task_success
            + 0.20 * self.test_pass_rate
            + 0.15 * self.scope_expansions
            + 0.10 * self.irrelevant_files
            + 0.10 * self.token_cost
            + 0.10 * self.override_rate
            + 0.05 * self.false_warning_rate
        )


@dataclass
class EvalTask:
    """A single replay task in the eval corpus."""
    commit_hash: str
    task_description: str
    expected_files: List[str] = field(default_factory=list)
    expected_constraints: List[str] = field(default_factory=list)
    expected_tests: List[str] = field(default_factory=list)
    baseline_tokens: int = 0


@dataclass
class EvalCorpus:
    """Collection of replay tasks for evaluation."""
    tasks: List[EvalTask] = field(default_factory=list)
    min_tasks: int = 30
    repo_root: str = ""
    baseline_candidate: str = ""

    @property
    def valid(self) -> bool:
        return len(self.tasks) >= self.min_tasks


@dataclass
class EvalRun:
    """Complete results from evaluating a candidate."""
    candidate_id: str
    corpus_id: str
    gates: List[GateResult] = field(default_factory=list)
    primary: Optional[EditFrontierScore] = None
    secondary: Optional[DownstreamScore] = None
    fitness: float = 0.0
    timestamp: str = ""
    observations: int = 0
