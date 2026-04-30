# Dotscope Live Trial Corpus: Pre-Registration

**Status:** Pre-registration. Authored before any public-eligible pairs run.
**Harness:** Live trial harness, schema v1, tag `trial-schema-v1`.
**Purpose:** Establish corpus selection criteria, hypothesis, and reporting commitments before data exists, so the resulting public claim is defensible against the cherry-picking critique.

---

## Hypothesis

Dotscope's effect on agentic coding outcomes scales with the architectural complexity of the task. Specifically: as the number of files modified and modules crossed by a correct fix increases, the gap between dotscope-armed agents and baseline agents widens.

This hypothesis is the empirical question the corpus is designed to answer. It can be wrong. If dotscope's effect is flat across task complexity, or only shows on simple tasks, the published report will say so.

---

## Repo Bracket

Eligible repos must satisfy all of the following:

- 200K to 800K tokens of eligible text after dotscope's ignore rules.
- Strong unit-test infrastructure with hermetic, reproducible runs.
- Active issue tracker with closed bug-fix PRs as ground truth.
- Single primary language. Python preferred for first corpus (mature agent ecosystem, exemplary test discipline at this size class).
- Stable architectural shape (no major rewrite mid-corpus).

Repos below 200K tokens are excluded because retrieval barely matters at that size — the whole repo fits in agent context. Repos above 800K tokens are excluded because per-pair time exceeds the 8-hour public-claim cap and ingest fidelity becomes a confound.

---

## Selected Repos

Three repos for the first corpus, picked for distinct architectural shapes within the bracket:

**SQLAlchemy.** Genuine architectural seams (Core vs ORM, dialect layer, connection pooling, unit-of-work). Highest expected effect size per pair, highest expected variance. Load-bearing for the hypothesis: if dotscope's signal can't survive here, the thesis is in trouble.

**Pydantic (v2).** Coherent recent codebase shape, strong tests, fixes commonly cross the validation pipeline, type system, and JSON schema generation. Mid-bracket size, mid-complexity tasks, mid variance. Tests architectural generalization beyond ORM-shaped codebases.

**pytest.** Cleanest architectural shape of the three, exemplary self-test discipline, plugin-system seams provide real cross-module crossings without the variance of SQLAlchemy. Lower expected effect size, lower variance. Acts as ballast for CI tightness and cross-project aggregation.

This cut yields three repos with materially different architectures: ORM/data, validation/type, plugin/runner. If the effect generalizes across these three shapes, the claim is more than Python-conditional or domain-conditional.

**Cut criterion (verified before any pair runs):** Pull the most recent 30 closed bug-fix PRs from each repo. Count files modified, modules involved, and presence of regression tests. A repo qualifies if at least 60% of those PRs meet the within-repo task criteria below. A repo that fails this gate is dropped and replaced (Django subsystem-scoped or Celery as next candidates).

---

## Within-Repo Task Criteria

Tasks for the corpus must be derived from closed bug-fix PRs satisfying:

- 3 or more files modified in the fix.
- 2 or more modules involved (not just multiple files in one directory).
- Regression test added or modified as part of the fix.
- Estimated agent-time scope under 2 hours per arm.
- Test-deltable: the validation gate is a concrete command (`pytest path/to/test`) that passed after the fix and would have failed before.

Tasks not meeting all five criteria are excluded from the public corpus, regardless of how interesting they are.

---

## Portfolio Shape

Target 10 hard tasks per repo, 30 tasks total, 30 pairs total. Each pair is one dotscope-arm trial plus one baseline-arm trial on the same task, randomized arm order, independent worktrees from the same `base_ref`.

The N >= 30 paired pairs gate prints the public report. If pairs flake out (validation hermeticity tier-down, integrity failure, asymmetric measurement), the corpus extends with replacement tasks from the same repos until 30 valid pairs land.

Cross-project aggregation is mandatory: per-project deltas reported alongside the aggregate. The aggregate is the headline number. Per-project deltas tell the reader which architectural shapes carry the effect.

---

## Frozen Protocol Parameters

Locked before any pair runs. Changes invalidate accumulated pairs and require restart.

- **Agent and client:** Claude Code, current production model.
- **Model:** Frozen at corpus start; recorded in every trial record.
- **Token measurement boundary:** Agent-boundary, Tier B (tokenizer hook with declared encoding). Symmetric across both arms per pair.
- **Worktree policy:** Independent per arm, both clean from the same `base_ref`. `repo_state_hash` recorded at trial start; mismatched hashes invalidate the pair.
- **Validation runs:** 2 per validation command, all-must-pass, pass/fail asymmetry tiers down as flaky.
- **Arm order:** Randomized per pair. Order recorded in trial record.
- **Trial timeout:** 4 hours default. Trials exceeding 8 hours are auto-tiered-down regardless of completion.

---

## Publication Commitments

The report published alongside the public claim will include:

- This pre-registration document, unchanged from the version committed before pair execution begins.
- Aggregate metrics: `paired_token_delta_pct` and `paired_success_rate_delta` with bootstrap 95% CIs.
- Per-project deltas for each of the three repos with the same metrics and CIs.
- `full_corpus_compression_pct` co-printed and labeled illustrative, not a productivity claim.
- Sample size as paired pairs (N=30 minimum), not trials.
- CI method per metric (bootstrap percentile, fixed seed, 10000 resamples for paired deltas; Wilson for single-arm rates).
- Repo and date window for the corpus.
- Number of tasks excluded post-execution (flaky validation, integrity failure, etc.) and exclusion reasons.
- Any deviation from this pre-registration document, including the specific deviation, the reason, and what it implies for claim defensibility.

The report will not include:

- Curated subsets of the corpus selected post-hoc to improve the headline number.
- Token reduction claims without paired success metrics on the same trials.
- Cross-project aggregate without per-project deltas.

---

## What Could Falsify the Hypothesis

- Per-pair `paired_token_delta_pct` shows no correlation with task complexity (files modified, modules crossed). Effect exists but is flat.
- `paired_success_rate_delta` is statistically indistinguishable from zero across the corpus. Token reduction without outcome improvement.
- Per-project deltas diverge sharply (one repo carries the entire signal; the other two are noise). Effect is not architectural-generality, it's repo-specific.
- 95% CI half-width exceeds 5pp on the aggregate metric at N=30. Effect size is too small or variance too high to support a public claim at this corpus size.

Each of these outcomes is a publishable result. The harness gates ensure the report prints honestly in all cases.

---

## Pre-Registration Hash

This document is committed to the dotscope repo before pair execution begins. The commit SHA and SHA-256 hash of this file at registration time will be recorded in every trial record's metadata. The report will reproduce both, allowing readers to verify that no post-hoc edits changed the registered criteria.

**Pre-registration commit:** _to be filled at registration_
**Pre-registration document hash:** _to be filled at registration_
