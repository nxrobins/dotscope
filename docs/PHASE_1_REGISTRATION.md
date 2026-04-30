# Phase 1 Registration — Human-Readable Record

This note records the live-trial pre-registration in prose so it can be cited
without grepping JSON or reading code. Authoritative machine state lives in
[trial-pre-registration.json](trial-pre-registration.json) and
[trial-pre-registration.sha256](trial-pre-registration.sha256); this file
exists for narrative history and outside-reader verification.

## Registered values

| Field | Value |
| --- | --- |
| Pre-registration document | [`docs/trial-pre-registration.md`](trial-pre-registration.md) |
| Pre-registration document hash (SHA-256) | `1d5420b9d170752329ed764d024cf9f997f1d36b61ea4e35a24ccfd67aaad70d` |
| Pre-registration commit (the commit that introduced the doc) | `7c8c6c528365c190ced99da837a30838d9147cd8` |
| Pre-registration tag | `trial-pre-registration-v1` (points at the harness-wiring commit `80d5d79`) |
| Harness tag | `trial-schema-v1` |
| Harness commit | `57383e4a3981b4eebd97df443510530b9f5c60c6` |

## Recorded deviations from pre-reg

Both deviations are baked into the harness's `report()` output. They appear in
every public report so readers see the full claim shape, not just the
headline number.

### `regression_test_modified_only`

- **From:** pre-reg line 53 (regression test "added or modified")
- **To:** "modified" only
- **Reason:** the orchestrator's pre-flight regression-verification gate
  (Phase 3) cannot soundly verify *added* regression tests. Test files
  added in a fix frequently depend on fixtures or modules also added by
  the same PR; running them on `pr_parent_sha` produces collection
  errors, not a clean fail. Implementing test-cherry-pick logic to
  resolve this has unbounded scope and brittle failure modes.
- **Implication for defensibility:** the qualifying pool shrinks. PRs
  with `regression_test_status == "added"` are tracked in cut-score
  output as `qualifies_diagnostic` but are excluded from
  `qualifies_public`. If any primary repo's modified-only qualifying
  rate falls below 60%, fallback selection or pool-widening is an
  operator decision per pre-reg line 43.

### `token_fidelity_tier_a`

- **From:** pre-reg line 77 ("Tier B (tokenizer hook with declared
  encoding)")
- **To:** Tier A (SDK provider-reported via `AssistantMessage.usage`)
- **Reason:** Anthropic does not publish an offline tokenizer for
  current Claude models. The only practical agent-boundary measurement
  paths are `client.messages.count_tokens` (network call per turn) and
  the SDK event stream's `usage` object (zero-latency, in-process).
  Both are provider-reported, which the spec calls Tier A.
- **Implication:** the harness's public-eligibility gate at
  [dotscope/trial.py:756](../dotscope/trial.py) accepts
  `token_fidelity ∈ {A, B}`, so Tier A is sufficient for public
  claims. The pre-reg's commitment to Tier B is downgraded to Tier A
  with this rationale recorded.

## Verification

To verify the registration without reading code:

```sh
python -c "import hashlib, pathlib; \
  print(hashlib.sha256(pathlib.Path('docs/trial-pre-registration.md').read_bytes()).hexdigest())"
# expect: 1d5420b9d170752329ed764d024cf9f997f1d36b61ea4e35a24ccfd67aaad70d

git show trial-pre-registration-v1 --stat
# expect Commit B "Wire pre-registration into trial harness" with
# tests/test_trial.py and dotscope/trial.py modifications.

git show 7c8c6c5 -- docs/trial-pre-registration.md | head -10
# expect the doc as committed in Commit A.
```

`docs/trial-pre-registration.md` is pinned to LF line endings via
[`.gitattributes`](../.gitattributes); the hash is stable across
platforms.

## Lock semantics

Any change to `docs/trial-pre-registration.md` (or its hash in the
sidecar) invalidates accumulated trial pairs. The harness embeds
`pre_registration.doc_sha256` into every trial JSON at start time and
adds it to the agreement-key set in `analyze_pair`; pairs whose two
arms ran against different doc hashes fail public eligibility. The
practical effect: an edit to the registration document during a
corpus run forces N=30 to restart from zero.
