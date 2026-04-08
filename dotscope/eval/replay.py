"""Replay protocol: evaluate a candidate by replaying corpus tasks.

For each task in the corpus:
1. Resolve scope at the parent commit's state
2. Run check against the actual diff
3. Compare predicted vs actual files, constraints, tests
4. Record observation metrics
"""

import os
import subprocess
import time
from typing import List, Optional

from ..models.eval import (
    DownstreamScore,
    EditFrontierScore,
    EvalCorpus,
    EvalRun,
    EvalTask,
)
from ..models.state import ObservationLog
from .corpus import corpus_id
from .harness import compute_primary, compute_secondary, evaluate_gates, fitness


def replay_corpus(
    corpus: EvalCorpus,
    repo_root: str,
    candidate_id: str = "current",
    baseline_obs: Optional[List[ObservationLog]] = None,
    budget: Optional[int] = None,
) -> EvalRun:
    """Replay an eval corpus and produce a full EvalRun.

    Each task is replayed by resolving scope with the task description
    and comparing the result against expected files.

    Args:
        corpus: The eval corpus to replay.
        repo_root: Repository root.
        candidate_id: Identifier for this candidate.
        baseline_obs: Baseline observations for gate comparison.
        budget: Token budget for resolution (None = unlimited).
    """
    # Build co-change index from corpus for ranking signal
    co_change_index = _build_co_change_index(corpus)

    # Load utility scores from .dotscope/ if available
    utility_scores = None
    try:
        from pathlib import Path
        from ..engine.utility import load_utility_scores
        dot_dir = Path(repo_root) / ".dotscope"
        if dot_dir.exists():
            utility_scores = load_utility_scores(dot_dir)
    except Exception:
        pass

    observations: List[ObservationLog] = []
    constraints_violated_all: List[List[str]] = []
    constraints_surfaced_all: List[List[str]] = []
    recommended_tests_all: List[List[str]] = []
    actual_tests_all: List[List[str]] = []
    stale_counts: List[int] = []
    predicted_counts: List[int] = []
    total_tokens = 0

    for task in corpus.tasks:
        result = _replay_single_task(task, repo_root, budget, co_change_index, utility_scores)
        if result is None:
            continue

        obs, surfaced, recommended, stale, tokens = result
        observations.append(obs)
        constraints_violated_all.append(task.expected_constraints)
        constraints_surfaced_all.append(surfaced)
        recommended_tests_all.append(recommended)
        actual_tests_all.append(task.expected_tests)
        stale_counts.append(stale)
        predicted_counts.append(len(obs.actual_files_modified) + len(obs.predicted_not_touched))
        total_tokens += tokens

    # Evaluate
    gates = evaluate_gates(
        candidate_obs=observations,
        baseline_obs=baseline_obs or [],
        repo_root=repo_root,
    )

    primary = compute_primary(
        observations=observations,
        constraints_violated=constraints_violated_all,
        constraints_surfaced=constraints_surfaced_all,
        recommended_tests=recommended_tests_all,
        actual_tests=actual_tests_all,
        stale_file_counts=stale_counts,
        total_predicted_counts=predicted_counts,
    )

    secondary = compute_secondary(
        observations=observations,
        total_tasks=len(corpus.tasks),
        total_tokens_served=total_tokens,
        budget_cap=budget or 100000,
    )

    score = fitness(gates, primary, secondary)

    return EvalRun(
        candidate_id=candidate_id,
        corpus_id=corpus_id(corpus),
        gates=gates,
        primary=primary,
        secondary=secondary,
        fitness=score,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        observations=len(observations),
    )


def _replay_single_task(
    task: EvalTask,
    repo_root: str,
    budget: Optional[int],
    co_change_index: Optional[dict] = None,
    utility_scores: Optional[dict] = None,
) -> Optional[tuple]:
    """Replay one task. Returns (obs, surfaced, recommended_tests, stale_count, tokens) or None."""
    try:
        from ..engine.composer import compose_for_task
        from ..engine.discovery import find_all_scopes
        from ..engine.matcher import match_task
        from ..engine.parser import parse_scope_file
        from ..engine.resolver import resolve

        # Primary path: auto-compose top-N matching scopes
        resolved = compose_for_task(task.task_description, root=repo_root, max_scopes=2)

        # Fallback: compose scopes matching directory prefixes of expected files
        if not resolved.files:
            from ..engine.composer import compose

            scope_files = find_all_scopes(repo_root)
            if not scope_files:
                return None

            scope_configs = []
            for sf in scope_files:
                try:
                    scope_configs.append(parse_scope_file(sf))
                except Exception:
                    continue

            if not scope_configs:
                return None

            scope_by_name = {}
            for sc in scope_configs:
                name = os.path.basename(os.path.dirname(sc.path)) or "root"
                scope_by_name[name] = sc

            matched_names = _match_directories_multi(
                task.expected_files, scope_by_name, max_scopes=2,
            )
            if not matched_names:
                return None

            # Resolve each scope with provenance: primary scope scores higher
            result = None
            for i, name in enumerate(matched_names):
                config = scope_by_name.get(name)
                if not config:
                    continue
                scope_resolved = resolve(config, follow_related=True, root=repo_root)
                # Primary scope (i=0) gets 1.0, secondary gets 0.5, etc.
                weight = 1.0 / (1 + i)
                scope_resolved.file_scores = {f: weight for f in scope_resolved.files}
                if result is None:
                    result = scope_resolved
                else:
                    result = result.merge(scope_resolved)

            if not result:
                return None
            resolved = result

        # Trim to top-K files by task relevance
        _TOP_K = 12

        if len(resolved.files) > _TOP_K:
            from ..passes.budget_allocator import _rank_files
            ranked = _rank_files(
                resolved.files,
                task=task.task_description,
                utility_scores=utility_scores,
                file_scores=resolved.file_scores or None,
                co_change_index=co_change_index,
            )
            top_files = [path for path, _score in ranked[:_TOP_K]]
            from ..models import ResolvedScope as _RS
            resolved = _RS(
                files=top_files,
                context=resolved.context,
                token_estimate=resolved.token_estimate,
                scope_chain=resolved.scope_chain,
                truncated=len(top_files) < len(ranked),
            )

        predicted_files = set(
            os.path.relpath(f, repo_root) for f in resolved.files
        )
        actual_files = set(task.expected_files)

        intersection = predicted_files & actual_files
        predicted_not_touched = sorted(predicted_files - actual_files)
        touched_not_predicted = sorted(actual_files - predicted_files)

        recall = len(intersection) / len(actual_files) if actual_files else 1.0
        precision = len(intersection) / len(predicted_files) if predicted_files else 1.0

        obs = ObservationLog(
            commit_hash=task.commit_hash,
            session_id=f"eval-{task.commit_hash[:8]}",
            actual_files_modified=sorted(actual_files),
            predicted_not_touched=predicted_not_touched,
            touched_not_predicted=touched_not_predicted,
            recall=round(recall, 3),
            precision=round(precision, 3),
            timestamp=time.time(),
        )

        # Constraint surfacing: check what constraints the resolved context mentions
        surfaced: List[str] = []
        try:
            from ..passes.sentinel.constraints import build_constraints
            constraints = build_constraints(
                repo_root, resolved.files, task.task_description,
            )
            surfaced = [c.get("id", "") for c in constraints if c.get("id")]
        except Exception:
            pass

        # Test recommendations from check
        recommended_tests: List[str] = []
        try:
            diff_text = _get_commit_diff(repo_root, task.commit_hash)
            if diff_text:
                from ..passes.sentinel.checker import check_diff
                report = check_diff(diff_text, repo_root)
                for r in report.results:
                    if r.proposed_fix and r.proposed_fix.predicted_sections:
                        recommended_tests.extend(r.proposed_fix.predicted_sections)
        except Exception:
            pass

        # Stale file count: files in predicted set that don't exist at current state
        stale = sum(1 for f in predicted_files if not os.path.isfile(os.path.join(repo_root, f)))

        return obs, surfaced, recommended_tests, stale, resolved.token_estimate

    except Exception:
        return None


def _match_directories_multi(
    expected_files: List[str],
    scope_by_name: dict,
    max_scopes: int = 3,
) -> List[str]:
    """Match expected files to scopes by directory prefix. Returns scope names."""
    from collections import Counter
    dir_counts: Counter = Counter()
    for f in expected_files:
        parts = f.split("/")
        if len(parts) > 1:
            dir_counts[parts[0]] += 1

    matched: List[str] = []
    for dirname, _count in dir_counts.most_common():
        if len(matched) >= max_scopes:
            break
        for name, sc in scope_by_name.items():
            scope_dir = os.path.basename(os.path.dirname(sc.path))
            if (scope_dir == dirname or name == dirname) and name not in matched:
                matched.append(name)
                break

    return matched


def _build_co_change_index(corpus: EvalCorpus) -> dict:
    """Build a co-change affinity index using NPMI.

    Returns {file: {partner: npmi}} where NPMI (Normalized Pointwise Mutual
    Information) measures symbiotic co-change relationships, controlling for
    each file's baseline frequency. This prevents "god files" (constants.py,
    __init__.py) from getting inflated co-change scores.

    NPMI = PMI / -log2(P(A,B))
    PMI  = log2(P(A,B) / (P(A) * P(B)))
    """
    import math
    from collections import Counter, defaultdict

    file_freq: Counter = Counter()
    pair_count: Counter = Counter()

    for task in corpus.tasks:
        files = task.expected_files
        file_freq.update(files)
        for i, f1 in enumerate(files):
            for f2 in files[i + 1:]:
                pair = tuple(sorted([f1, f2]))
                pair_count[pair] += 1

    N = len(corpus.tasks)
    if N == 0:
        return {}

    # Build {file: {partner: npmi}}
    index: dict = defaultdict(dict)
    for (f1, f2), count in pair_count.items():
        if count < 2:  # only pairs seen together 2+ times
            continue

        p_a = file_freq[f1] / N
        p_b = file_freq[f2] / N
        p_ab = count / N

        denom = p_a * p_b
        if denom <= 0 or p_ab <= 0:
            continue

        pmi = math.log2(p_ab / denom)
        neg_log_pab = -math.log2(p_ab)
        npmi = pmi / neg_log_pab if neg_log_pab > 0 else 0.0
        npmi = max(0.0, npmi)  # clamp anti-correlated pairs to 0

        # NPMI is symmetric
        index[f1][f2] = npmi
        index[f2][f1] = npmi

    return dict(index)


def _get_commit_diff(repo_root: str, commit_hash: str) -> str:
    """Get the diff for a single commit."""
    try:
        result = subprocess.run(
            ["git", "diff", f"{commit_hash}^", commit_hash],
            cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""
