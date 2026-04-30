import hashlib
import json
import subprocess
import sys

import pytest

from dotscope.trial import (
    PublicReportError,
    TRIAL_EVENT_SCHEMA_HEADER,
    TrialError,
    TrialStore,
    classify_validation,
    load_pre_registration,
)


def _init_repo(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"],
        check=True,
    )
    (tmp_path / "app.py").write_text("print('hi')\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "app.py"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return tmp_path


def _install_pre_registration(repo_root, doc_body="# fixture pre-reg\n", commit="aaaa1111"):
    docs_dir = repo_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_path = docs_dir / "trial-pre-registration.md"
    doc_path.write_bytes(doc_body.encode("utf-8"))
    doc_hash = hashlib.sha256(doc_path.read_bytes()).hexdigest()
    sidecar = {
        "schema_version": 1,
        "doc_path": "docs/trial-pre-registration.md",
        "doc_sha256": doc_hash,
        "registered_commit": commit,
        "tag": "trial-pre-registration-v1",
        "harness_tag": "trial-schema-v1",
        "harness_commit": "57383e4a3981b4eebd97df443510530b9f5c60c6",
        "deviations": [
            {"id": "fixture_dev_1", "from": "x", "to": "y", "reason": "test"},
        ],
    }
    (docs_dir / "trial-pre-registration.json").write_text(
        json.dumps(sidecar, indent=2), encoding="utf-8"
    )
    (docs_dir / "trial-pre-registration.sha256").write_text(
        f"{doc_hash}  trial-pre-registration.md\n", encoding="utf-8"
    )
    return doc_hash


def _make_public_pair(store, index, dotscope_tokens=500, baseline_tokens=1000):
    pair = store.create_pair(
        task=f"task {index}",
        model="gpt-test",
        client="codex",
        project="project-a",
        pair_id=f"pair_{index}",
        order_policy="alternating",
    )
    for arm, tokens in (("dotscope", dotscope_tokens), ("baseline", baseline_tokens)):
        trial = {
            "schema_version": 1,
            "trial_id": f"trial_{index}_{arm}",
            "pair_id": pair["pair_id"],
            "arm": arm,
            "status": "finished",
            "task": pair["task"],
            "model": pair["model"],
            "client": pair["client"],
            "project_id": pair["project_id"],
            "base_ref": pair["base_ref"],
            "worktree_path": str(store.root),
            "repo_state_hash": "abc:clean",
            "head": "abc",
            "clean_start": True,
            "dirty_paths": [],
            "token_boundary": "agent",
            "token_fidelity": "A",
            "capture_method": "provider-usage",
            "tokenizer_encoding": "",
            "timeout_hours": 4.0,
            "public_timeout_ok": True,
            "started_at": "2026-01-01T00:00:00Z",
            "expires_at": "2026-01-01T04:00:00Z",
            "ended_at": "2026-01-01T00:10:00Z",
            "validation_status": "success",
            "validation_runs": [{"run": 1, "command": "test", "return_code": 0, "passed": True}],
            "commits": ["HEAD"],
            "committed_files": ["app.py"],
            "integrity": {"checked": False, "passed": None, "issues": []},
        }
        store._save_trial(trial)
        store._initialize_events(trial["trial_id"])
        store.append_event(trial["trial_id"], {
            "type": "token_usage",
            "source": "provider",
            "input_tokens": tokens,
            "token_boundary": "agent",
            "token_fidelity": "A",
            "capture_method": "provider-usage",
            "tokenizer_encoding": "",
        })
        trial["integrity"] = store.check_integrity(trial["trial_id"])
        store._save_trial(trial)


class TestTrialLifecycle:
    def test_pair_new_and_start_records_clean_state(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))

        pair = store.create_pair(
            task="fix auth",
            model="gpt-test",
            client="codex",
            project="demo",
            order_policy="alternating",
        )
        trial = store.start_trial(pair["pair_id"], "dotscope", token_fidelity="A")

        assert trial["clean_start"] is True
        assert trial["repo_state_hash"].endswith(":clean")
        assert trial["project_id"] == "demo"
        assert store.get_active_trial()["trial_id"] == trial["trial_id"]

        event_path = repo / ".dotscope" / "trials" / "events" / f"{trial['trial_id']}.jsonl"
        first_line = json.loads(event_path.read_text().splitlines()[0])
        assert first_line == TRIAL_EVENT_SCHEMA_HEADER

    def test_dirty_start_is_diagnostic(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        pair = store.create_pair(task="dirty task", model="gpt-test", client="codex")
        (repo / "dirty.py").write_text("x = 1\n")

        trial = store.start_trial(pair["pair_id"], "baseline")

        assert trial["clean_start"] is False
        assert "dirty.py" in trial["dirty_paths"]

    def test_expired_active_trial_is_reaped(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        pair = store.create_pair(task="stale task", model="gpt-test", client="codex")
        trial = store.start_trial(pair["pair_id"], "dotscope")
        trial["expires_at"] = "2000-01-01T00:00:00Z"
        store._save_trial(trial)

        assert store.get_active_trial() is None
        expired = store.load_trial(trial["trial_id"])
        assert expired["status"] == "expired"

    def test_validation_semantics(self):
        assert classify_validation([
            {"run": 1, "passed": True},
            {"run": 2, "passed": True},
        ]) == "success"
        assert classify_validation([
            {"run": 1, "passed": False},
            {"run": 2, "passed": False},
        ]) == "failure"
        assert classify_validation([
            {"run": 1, "passed": True},
            {"run": 2, "passed": False},
        ]) == "flaky"


class TestTrialPublicGates:
    def test_pair_rejects_asymmetric_measurement_boundary(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        pair = store.create_pair(task="same task", model="gpt-test", client="codex")

        dotscope = store.start_trial(
            pair["pair_id"],
            "dotscope",
            token_boundary="dotscope",
            token_fidelity="A",
        )
        store.record_tokens(
            input_tokens=500,
            token_boundary="dotscope",
            token_fidelity="A",
            trial_id=dotscope["trial_id"],
        )
        store.finish_trial(
            trial_id=dotscope["trial_id"],
            commits=["HEAD"],
            validations=[f"{sys.executable} -c \"pass\""],
            validation_runs=2,
        )

        baseline = store.start_trial(
            pair["pair_id"],
            "baseline",
            token_boundary="agent",
            token_fidelity="A",
        )
        store.record_tokens(
            input_tokens=1000,
            token_boundary="agent",
            token_fidelity="A",
            trial_id=baseline["trial_id"],
        )
        store.finish_trial(
            trial_id=baseline["trial_id"],
            commits=["HEAD"],
            validations=[f"{sys.executable} -c \"pass\""],
            validation_runs=2,
        )

        comparison = store.compare_pair(pair["pair_id"])
        assert comparison["public_valid"] is False
        assert any("token_boundary" in reason for reason in comparison["reasons"])

    def test_public_report_passes_with_valid_pairs_and_pinned_ci(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        for index in range(60):
            _make_public_pair(store, index)

        report = store.report(public=True)

        assert report["valid_public_pairs"] == 60
        assert all(gate["passed"] for gate in report["gates"])
        assert report["statistics"]["bootstrap_resamples"] == 10000
        assert report["statistics"]["bootstrap_method"] == "percentile"
        assert report["metrics"]["paired_token_delta_pct"]["mean"] == 50.0
        assert report["metrics"]["paired_token_delta_pct"]["ci_half_width_pp"] == 0.0
        assert report["projects"]["project-a"]["project_override"] is True

    def test_public_report_refuses_when_n_is_pairs_not_trials(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        _make_public_pair(store, 1)

        with pytest.raises(PublicReportError) as exc:
            store.report(public=True)

        gate = next(g for g in exc.value.report["gates"] if g["name"] == "minimum_pairs")
        assert gate["passed"] is False
        assert gate["value"] == 1
        assert "60 trials" in gate["detail"]


class TestTrialPreRegistration:
    def test_load_returns_none_when_sidecar_absent(self, tmp_path):
        repo = _init_repo(tmp_path)
        assert load_pre_registration(str(repo)) is None

    def test_load_verifies_doc_hash(self, tmp_path):
        repo = _init_repo(tmp_path)
        doc_hash = _install_pre_registration(repo, commit="cafe1234")
        loaded = load_pre_registration(str(repo))
        assert loaded is not None
        assert loaded["doc_sha256"] == doc_hash
        assert loaded["commit"] == "cafe1234"
        assert loaded["tag"] == "trial-pre-registration-v1"
        assert loaded["deviations"][0]["id"] == "fixture_dev_1"

    def test_load_raises_on_doc_hash_mismatch(self, tmp_path):
        repo = _init_repo(tmp_path)
        _install_pre_registration(repo)
        (repo / "docs" / "trial-pre-registration.md").write_bytes(b"tampered\n")
        with pytest.raises(TrialError) as exc:
            load_pre_registration(str(repo))
        assert "hash mismatch" in str(exc.value)

    def test_load_raises_when_doc_missing_but_sidecar_present(self, tmp_path):
        repo = _init_repo(tmp_path)
        _install_pre_registration(repo)
        (repo / "docs" / "trial-pre-registration.md").unlink()
        with pytest.raises(TrialError) as exc:
            load_pre_registration(str(repo))
        assert "doc missing" in str(exc.value)

    def test_start_trial_embeds_pre_registration(self, tmp_path):
        repo = _init_repo(tmp_path)
        doc_hash = _install_pre_registration(repo, commit="b00b1e55")
        store = TrialStore(str(repo))
        pair = store.create_pair(task="reg task", model="gpt-test", client="codex")
        trial = store.start_trial(pair["pair_id"], "dotscope", token_fidelity="A")
        assert trial["pre_registration"]["doc_sha256"] == doc_hash
        assert trial["pre_registration"]["commit"] == "b00b1e55"

        persisted = store.load_trial(trial["trial_id"])
        assert persisted["pre_registration"]["doc_sha256"] == doc_hash

    def test_start_trial_records_none_when_no_registration(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        pair = store.create_pair(task="no-reg", model="gpt-test", client="codex")
        trial = store.start_trial(pair["pair_id"], "dotscope", token_fidelity="A")
        assert trial["pre_registration"] is None

    def test_pair_invalid_when_arms_disagree_on_doc_sha256(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        _make_public_pair(store, 1)
        # Simulate registration drift between arms by tampering the saved trials.
        for arm in ("dotscope", "baseline"):
            trial = store.load_trial(f"trial_1_{arm}")
            trial["pre_registration"] = {
                "doc_sha256": "hash-a" if arm == "dotscope" else "hash-b",
                "commit": "x",
                "tag": "t",
                "deviations": [],
            }
            store._save_trial(trial)
        comparison = store.compare_pair("pair_1")
        assert comparison["public_valid"] is False
        assert any(
            "pre_registration.doc_sha256" in reason for reason in comparison["reasons"]
        )

    def test_report_includes_pre_registration_and_deviations(self, tmp_path):
        repo = _init_repo(tmp_path)
        _install_pre_registration(repo, commit="deadbeef")
        store = TrialStore(str(repo))
        report = store.report(public=False)
        assert report["pre_registration"]["commit"] == "deadbeef"
        assert report["pre_registration"]["doc_sha256"]
        assert report["deviations"][0]["id"] == "fixture_dev_1"

    def test_report_returns_none_pre_reg_when_unregistered(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        report = store.report(public=False)
        assert report["pre_registration"] is None
        assert report["deviations"] == []


class TestTrialTokenAccounting:
    def test_default_token_accounting_policy_recorded(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        pair = store.create_pair(task="acct", model="m", client="c")
        trial = store.start_trial(pair["pair_id"], "dotscope", token_fidelity="A")
        assert trial["token_accounting_policy"] == "billed_input_sum"

    def test_custom_token_accounting_policy_recorded(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        pair = store.create_pair(task="acct", model="m", client="c")
        trial = store.start_trial(
            pair["pair_id"], "dotscope", token_fidelity="A",
            token_accounting_policy="input_only",
        )
        assert trial["token_accounting_policy"] == "input_only"

    def test_unknown_token_accounting_policy_rejected(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        pair = store.create_pair(task="acct", model="m", client="c")
        with pytest.raises(TrialError):
            store.start_trial(
                pair["pair_id"], "dotscope", token_fidelity="A",
                token_accounting_policy="banana",
            )

    def test_record_tokens_persists_cache_components(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        pair = store.create_pair(task="cache", model="m", client="c")
        trial = store.start_trial(pair["pair_id"], "dotscope", token_fidelity="A")
        store.record_tokens(
            input_tokens=1500,
            token_boundary="agent",
            token_fidelity="A",
            cache_creation_input_tokens=200,
            cache_read_input_tokens=800,
            turn_id="turn-1",
            trial_id=trial["trial_id"],
        )
        events = store.load_events(trial["trial_id"])
        token_event = next(e for e in events if e.get("type") == "token_usage")
        assert token_event["input_tokens"] == 1500
        assert token_event["cache_creation_input_tokens"] == 200
        assert token_event["cache_read_input_tokens"] == 800
        assert token_event["turn_id"] == "turn-1"

    def test_record_tokens_rejects_negative_cache(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        pair = store.create_pair(task="neg", model="m", client="c")
        trial = store.start_trial(pair["pair_id"], "dotscope", token_fidelity="A")
        with pytest.raises(TrialError):
            store.record_tokens(
                input_tokens=10,
                token_boundary="agent",
                token_fidelity="A",
                cache_creation_input_tokens=-1,
                trial_id=trial["trial_id"],
            )

    def test_record_tokens_rejects_duplicate_turn_id(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        pair = store.create_pair(task="dup", model="m", client="c")
        trial = store.start_trial(pair["pair_id"], "dotscope", token_fidelity="A")
        store.record_tokens(
            input_tokens=100,
            token_boundary="agent",
            token_fidelity="A",
            turn_id="turn-1",
            trial_id=trial["trial_id"],
        )
        with pytest.raises(TrialError) as exc:
            store.record_tokens(
                input_tokens=200,
                token_boundary="agent",
                token_fidelity="A",
                turn_id="turn-1",
                trial_id=trial["trial_id"],
            )
        assert "duplicate turn_id" in str(exc.value)

    def test_record_tokens_allows_multiple_none_turn_id(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        pair = store.create_pair(task="none-tid", model="m", client="c")
        trial = store.start_trial(pair["pair_id"], "dotscope", token_fidelity="A")
        store.record_tokens(
            input_tokens=100,
            token_boundary="agent",
            token_fidelity="A",
            trial_id=trial["trial_id"],
        )
        # second call with no turn_id should not raise — None turn_id means
        # untracked-turn, multiple are OK
        store.record_tokens(
            input_tokens=200,
            token_boundary="agent",
            token_fidelity="A",
            trial_id=trial["trial_id"],
        )
        events = store.load_events(trial["trial_id"])
        token_events = [e for e in events if e.get("type") == "token_usage"]
        assert len(token_events) == 2

    def test_pair_invalid_when_arms_disagree_on_accounting_policy(self, tmp_path):
        repo = _init_repo(tmp_path)
        store = TrialStore(str(repo))
        _make_public_pair(store, 1)
        for arm, policy in (("dotscope", "billed_input_sum"), ("baseline", "input_only")):
            trial = store.load_trial(f"trial_1_{arm}")
            trial["token_accounting_policy"] = policy
            store._save_trial(trial)
        comparison = store.compare_pair("pair_1")
        assert comparison["public_valid"] is False
        assert any(
            "token_accounting_policy" in reason for reason in comparison["reasons"]
        )
