"""Tests for the eval harness: fitness function properties, gates, metrics."""

import pytest

from dotscope.models.eval import (
    DownstreamScore,
    EditFrontierScore,
    EvalCorpus,
    EvalRun,
    EvalTask,
    GateResult,
)
from dotscope.models.state import ObservationLog
from dotscope.eval.harness import (
    compute_primary,
    compute_secondary,
    evaluate_gates,
    fitness,
    _mean,
    _invariant_recall,
    _test_precision,
    _freshness_accuracy,
)
from dotscope.eval.compare import compare_runs, MetricDelta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_obs(recall=0.8, precision=0.7, predicted_not_touched=None,
              touched_not_predicted=None, actual_files=None):
    return ObservationLog(
        commit_hash="abc12345",
        session_id="s1",
        actual_files_modified=actual_files or ["a.py", "b.py"],
        predicted_not_touched=predicted_not_touched or [],
        touched_not_predicted=touched_not_predicted or [],
        recall=recall,
        precision=precision,
        timestamp=1000.0,
    )


def _passing_gates():
    return [
        GateResult(name="correctness", passed=True, value=0.8, threshold=0.78),
        GateResult(name="freshness", passed=True, value=0.1, threshold=0.1),
        GateResult(name="stability", passed=True, value=0.0, threshold=0.0),
        GateResult(name="resolve_latency", passed=True, value=100.0, threshold=500.0),
        GateResult(name="check_latency", passed=True, value=200.0, threshold=1000.0),
        GateResult(name="no_worktree_churn", passed=True, value=0.0, threshold=0.0),
    ]


# ---------------------------------------------------------------------------
# Gate failure → fitness = 0
# ---------------------------------------------------------------------------

class TestGateShortCircuit:
    def test_all_gates_pass(self):
        gates = _passing_gates()
        primary = EditFrontierScore(mean_f1=0.8, mean_f2=0.8, invariant_recall=0.9,
                                    test_precision=0.85, freshness_accuracy=0.95)
        secondary = DownstreamScore(task_success=0.7, test_pass_rate=0.8)
        assert fitness(gates, primary, secondary) > 0

    def test_single_gate_failure_zeros_fitness(self):
        gates = _passing_gates()
        gates[0] = GateResult(name="correctness", passed=False, value=0.5, threshold=0.78)
        primary = EditFrontierScore(mean_f1=1.0, mean_f2=1.0, invariant_recall=1.0,
                                    test_precision=1.0, freshness_accuracy=1.0)
        secondary = DownstreamScore(task_success=1.0, test_pass_rate=1.0)
        assert fitness(gates, primary, secondary) == 0.0

    def test_all_gates_fail(self):
        gates = [GateResult(name=f"g{i}", passed=False, value=0, threshold=1)
                 for i in range(6)]
        primary = EditFrontierScore(mean_f1=1.0, mean_f2=1.0)
        secondary = DownstreamScore(task_success=1.0)
        assert fitness(gates, primary, secondary) == 0.0


# ---------------------------------------------------------------------------
# Primary dominates secondary
# ---------------------------------------------------------------------------

class TestPrimaryDominance:
    def test_better_primary_always_wins(self):
        """A candidate with better primary beats one with perfect secondary."""
        gates = _passing_gates()

        better_primary = EditFrontierScore(
            mean_f1=0.9, mean_f2=0.9, invariant_recall=0.9,
            test_precision=0.9, freshness_accuracy=0.9,
        )
        worse_secondary = DownstreamScore()  # all zeros

        worse_primary = EditFrontierScore(
            mean_f1=0.5, mean_f2=0.5, invariant_recall=0.5,
            test_precision=0.5, freshness_accuracy=0.5,
        )
        perfect_secondary = DownstreamScore(
            task_success=1.0, test_pass_rate=1.0,
            scope_expansions=1.0, irrelevant_files=1.0,
            token_cost=1.0, override_rate=1.0,
            false_warning_rate=1.0,
        )

        f_better = fitness(gates, better_primary, worse_secondary)
        f_worse = fitness(gates, worse_primary, perfect_secondary)
        assert f_better > f_worse

    def test_secondary_breaks_ties(self):
        """When primary is identical, secondary determines winner."""
        gates = _passing_gates()
        same_primary = EditFrontierScore(
            mean_f1=0.8, mean_f2=0.8, invariant_recall=0.8,
            test_precision=0.8, freshness_accuracy=0.8,
        )

        better_secondary = DownstreamScore(task_success=0.9, test_pass_rate=0.9)
        worse_secondary = DownstreamScore(task_success=0.1, test_pass_rate=0.1)

        f_better = fitness(gates, same_primary, better_secondary)
        f_worse = fitness(gates, same_primary, worse_secondary)
        assert f_better > f_worse

    def test_secondary_contributes_at_most_001(self):
        """Secondary composite is scaled by 0.01."""
        gates = _passing_gates()
        primary = EditFrontierScore(mean_f1=0.5, mean_f2=0.5)
        perfect = DownstreamScore(
            task_success=1.0, test_pass_rate=1.0,
            scope_expansions=1.0, irrelevant_files=1.0,
            token_cost=1.0, override_rate=1.0,
            false_warning_rate=1.0,
        )
        zero = DownstreamScore()

        f_perfect = fitness(gates, primary, perfect)
        f_zero = fitness(gates, primary, zero)
        assert f_perfect - f_zero <= 0.011  # at most ~0.01 difference


# ---------------------------------------------------------------------------
# Fitness monotonicity
# ---------------------------------------------------------------------------

class TestMonotonicity:
    def test_higher_f1_higher_fitness(self):
        gates = _passing_gates()
        secondary = DownstreamScore()
        low = EditFrontierScore(mean_f1=0.3, mean_f2=0.3)
        high = EditFrontierScore(mean_f1=0.9, mean_f2=0.9)
        assert fitness(gates, high, secondary) > fitness(gates, low, secondary)

    def test_higher_invariant_recall_higher_fitness(self):
        gates = _passing_gates()
        secondary = DownstreamScore()
        low = EditFrontierScore(mean_f1=0.5, mean_f2=0.5, invariant_recall=0.3)
        high = EditFrontierScore(mean_f1=0.5, mean_f2=0.5, invariant_recall=0.9)
        assert fitness(gates, high, secondary) > fitness(gates, low, secondary)

    def test_higher_test_precision_higher_fitness(self):
        gates = _passing_gates()
        secondary = DownstreamScore()
        low = EditFrontierScore(mean_f1=0.5, mean_f2=0.5, test_precision=0.3)
        high = EditFrontierScore(mean_f1=0.5, mean_f2=0.5, test_precision=0.9)
        assert fitness(gates, high, secondary) > fitness(gates, low, secondary)

    def test_higher_freshness_higher_fitness(self):
        gates = _passing_gates()
        secondary = DownstreamScore()
        low = EditFrontierScore(mean_f1=0.5, mean_f2=0.5, freshness_accuracy=0.3)
        high = EditFrontierScore(mean_f1=0.5, mean_f2=0.5, freshness_accuracy=0.9)
        assert fitness(gates, high, secondary) > fitness(gates, low, secondary)


# ---------------------------------------------------------------------------
# Weight normalization
# ---------------------------------------------------------------------------

class TestWeightNormalization:
    def test_primary_weights_sum_to_one(self):
        assert abs(0.50 + 0.25 + 0.15 + 0.10 - 1.0) < 1e-9

    def test_secondary_weights_sum_to_one(self):
        assert abs(0.30 + 0.20 + 0.15 + 0.10 + 0.10 + 0.10 + 0.05 - 1.0) < 1e-9

    def test_perfect_primary_composite_is_one(self):
        perfect = EditFrontierScore(
            mean_f1=1.0, mean_f2=1.0, invariant_recall=1.0,
            test_precision=1.0, freshness_accuracy=1.0,
        )
        assert abs(perfect.composite - 1.0) < 1e-9

    def test_perfect_secondary_composite_is_one(self):
        perfect = DownstreamScore(
            task_success=1.0, test_pass_rate=1.0,
            scope_expansions=1.0, irrelevant_files=1.0,
            token_cost=1.0, override_rate=1.0,
            false_warning_rate=1.0,
        )
        assert abs(perfect.composite - 1.0) < 1e-9

    def test_zero_f1_primary_composite(self):
        """With F1=0 but no-data defaults for IR/TP/FA (1.0), composite = 0.50."""
        zero = EditFrontierScore()
        assert zero.composite == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# compute_primary from observations
# ---------------------------------------------------------------------------

class TestComputePrimary:
    def test_perfect_observations(self):
        obs = [_make_obs(recall=1.0, precision=1.0)]
        score = compute_primary(obs)
        assert score.mean_recall == 1.0
        assert score.mean_precision == 1.0
        assert score.mean_f1 == 1.0

    def test_multiple_observations_averaged(self):
        obs = [
            _make_obs(recall=1.0, precision=0.5),
            _make_obs(recall=0.5, precision=1.0),
        ]
        score = compute_primary(obs)
        assert score.mean_recall == 0.75
        assert score.mean_precision == 0.75

    def test_empty_observations(self):
        score = compute_primary([])
        assert score.mean_f1 == 0.0
        # No-data defaults: IR=1.0, TP=1.0, FA=1.0 → 0.25 + 0.15 + 0.10 = 0.50
        assert score.composite == pytest.approx(0.50)

    def test_invariant_recall_computation(self):
        ir = _invariant_recall(
            violated=[["c1", "c2"], ["c3"]],
            surfaced=[["c1"], ["c3"]],
        )
        # c1 surfaced of {c1,c2}, c3 surfaced of {c3} → 2/3
        assert abs(ir - 2 / 3) < 1e-9

    def test_invariant_recall_no_violations(self):
        assert _invariant_recall(None, None) == 1.0
        assert _invariant_recall([], []) == 1.0

    def test_test_precision_computation(self):
        tp = _test_precision(
            recommended=[["t1.py", "t2.py"], ["t3.py"]],
            actual=[["t1.py"], ["t3.py", "t4.py"]],
        )
        # t1 hit of {t1,t2}, t3 hit of {t3} → 2/3
        assert abs(tp - 2 / 3) < 1e-9

    def test_freshness_accuracy(self):
        fa = _freshness_accuracy(
            stale_counts=[2, 0],
            total_counts=[10, 10],
        )
        assert fa == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# compute_secondary
# ---------------------------------------------------------------------------

class TestComputeSecondary:
    def test_basic_computation(self):
        obs = [_make_obs(predicted_not_touched=["c.py"])]
        score = compute_secondary(
            observations=obs,
            tasks_completed_first_try=8,
            total_tasks=10,
            tests_passed_first_run=9,
            tests_run_first_run=10,
        )
        assert score.task_success == 0.8
        assert score.test_pass_rate == 0.9

    def test_irrelevant_files_from_observations(self):
        obs = [_make_obs(
            actual_files=["a.py"],
            predicted_not_touched=["b.py", "c.py", "d.py"],
        )]
        score = compute_secondary(observations=obs)
        # 3 irrelevant out of 4 total predicted → 1 - 0.75 = 0.25
        assert score.irrelevant_files == 0.25


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

class TestComparison:
    def test_better_candidate(self):
        baseline = EvalRun(
            candidate_id="base", corpus_id="c1", fitness=0.5,
            gates=_passing_gates(),
            primary=EditFrontierScore(mean_f1=0.5, mean_f2=0.5, mean_recall=0.5, mean_precision=0.5),
            secondary=DownstreamScore(task_success=0.5),
        )
        candidate = EvalRun(
            candidate_id="new", corpus_id="c1", fitness=0.7,
            gates=_passing_gates(),
            primary=EditFrontierScore(mean_f1=0.7, mean_f2=0.7, mean_recall=0.7, mean_precision=0.7),
            secondary=DownstreamScore(task_success=0.7),
        )
        report = compare_runs(baseline, candidate)
        assert report.verdict == "better"
        assert report.fitness_delta > 0

    def test_equivalent_candidates(self):
        run = EvalRun(
            candidate_id="same", corpus_id="c1", fitness=0.5,
            gates=_passing_gates(),
            primary=EditFrontierScore(mean_f1=0.5, mean_f2=0.5),
            secondary=DownstreamScore(),
        )
        report = compare_runs(run, run)
        assert report.verdict == "equivalent"
        assert report.fitness_delta == 0.0

    def test_gate_change_detected(self):
        baseline = EvalRun(
            candidate_id="base", corpus_id="c1",
            gates=[GateResult(name="stability", passed=True, value=0, threshold=0)],
            primary=EditFrontierScore(), secondary=DownstreamScore(),
        )
        candidate = EvalRun(
            candidate_id="new", corpus_id="c1",
            gates=[GateResult(name="stability", passed=False, value=1, threshold=0)],
            primary=EditFrontierScore(), secondary=DownstreamScore(),
        )
        report = compare_runs(baseline, candidate)
        assert any("BROKEN" in c for c in report.gate_changes)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_fitness_range(self):
        """Fitness is bounded [0.0, ~1.01]."""
        gates = _passing_gates()
        perfect_p = EditFrontierScore(
            mean_f1=1.0, mean_f2=1.0, invariant_recall=1.0,
            test_precision=1.0, freshness_accuracy=1.0,
        )
        perfect_s = DownstreamScore(
            task_success=1.0, test_pass_rate=1.0,
            scope_expansions=1.0, irrelevant_files=1.0,
            token_cost=1.0, override_rate=1.0,
            false_warning_rate=1.0,
        )
        f = fitness(gates, perfect_p, perfect_s)
        assert 0.0 <= f <= 1.02

    def test_zero_recall_zero_precision_f1(self):
        obs = [_make_obs(recall=0.0, precision=0.0)]
        score = compute_primary(obs)
        assert score.mean_f1 == 0.0

    def test_mean_of_empty(self):
        assert _mean([]) == 0.0

    def test_corpus_validity(self):
        corpus = EvalCorpus(tasks=[], min_tasks=30)
        assert not corpus.valid
        corpus.tasks = [EvalTask(commit_hash=f"h{i}", task_description="t") for i in range(30)]
        assert corpus.valid
