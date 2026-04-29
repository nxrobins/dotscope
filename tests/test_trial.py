import json
import subprocess
import sys

import pytest

from dotscope.trial import (
    PublicReportError,
    TRIAL_EVENT_SCHEMA_HEADER,
    TrialStore,
    classify_validation,
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
