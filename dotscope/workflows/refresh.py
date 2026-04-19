"""Runtime refresh queue, worker, and resolve-time freshness gate."""

import json
import os
import subprocess
import sys
import time
from typing import Dict, Iterable, List, Optional, Tuple

from ..paths import normalize_relative_path, scope_storage_key
from dotscope.engine.runtime_overlay import (
    find_effective_scope_with_source,
    logical_scope_path,
    replace_runtime_overlay,
)
from ..storage.incremental_state import (
    get_scope_refresh_epoch,
    load_incremental_state,
    mark_scopes_refreshed,
    reset_incremental_state,
    save_incremental_state,
    utc_now_iso,
)


REFRESH_WAIT_SECONDS = 1.0


def refresh_queue_path(root: str) -> str:
    return os.path.join(root, ".dotscope", "refresh_queue.json")


def refresh_status_path(root: str) -> str:
    return os.path.join(root, ".dotscope", "refresh_status.json")


def refresh_lock_path(root: str) -> str:
    return os.path.join(root, ".dotscope", "refresh.lock")


def _ensure_dot_dir(root: str) -> str:
    dot_dir = os.path.join(root, ".dotscope")
    os.makedirs(dot_dir, exist_ok=True)
    return dot_dir


def _default_status() -> Dict[str, object]:
    return {
        "running": False,
        "current_job": None,
        "current_targets": [],
        "last_success_at": "",
        "last_error_at": "",
        "last_error": "",
        "last_job_kind": None,
        "last_targets": [],
    }


def load_refresh_queue(root: str) -> List[Dict[str, object]]:
    path = refresh_queue_path(root)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []
    jobs = data.get("jobs", [])
    return jobs if isinstance(jobs, list) else []


def save_refresh_queue(root: str, jobs: Iterable[Dict[str, object]]) -> None:
    _ensure_dot_dir(root)
    with open(refresh_queue_path(root), "w", encoding="utf-8") as f:
        json.dump({"jobs": list(jobs)}, f, indent=2)


def load_refresh_status(root: str) -> Dict[str, object]:
    path = refresh_status_path(root)
    if not os.path.isfile(path):
        return _default_status()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return _default_status()

    status = _default_status()
    if isinstance(data, dict):
        status.update(data)
    return status


def save_refresh_status(root: str, status: Dict[str, object]) -> None:
    _ensure_dot_dir(root)
    with open(refresh_status_path(root), "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)


def _normalize_targets(targets: Iterable[str]) -> List[str]:
    normalized = []
    seen = set()
    for target in targets:
        clean = normalize_relative_path(target).rstrip("/")
        if not clean or clean in seen:
            continue
        normalized.append(clean)
        seen.add(clean)
    return sorted(normalized)


def _make_job(kind: str, targets: Iterable[str], reason: str = "") -> Dict[str, object]:
    return {
        "kind": kind,
        "targets": _normalize_targets(targets),
        "reason": reason,
        "enqueued_at": utc_now_iso(),
    }


def enqueue_scope_refresh(
    root: str,
    targets: Iterable[str],
    reason: str = "",
) -> Optional[Dict[str, object]]:
    targets = _normalize_targets(targets)
    if not targets:
        return None

    queue = load_refresh_queue(root)
    status = load_refresh_status(root)
    if status.get("running") and status.get("current_job") == "repo":
        return None
    if any(job.get("kind") == "repo" for job in queue):
        return None

    for job in queue:
        if job.get("kind") == "scope" and _normalize_targets(job.get("targets", [])) == targets:
            return job

    job = _make_job("scope", targets, reason=reason)
    queue.append(job)
    save_refresh_queue(root, queue)
    return job


def enqueue_repo_refresh(root: str, reason: str = "") -> Dict[str, object]:
    queue = load_refresh_queue(root)
    status = load_refresh_status(root)
    if status.get("running") and status.get("current_job") == "repo":
        return _make_job("repo", [], reason=reason)

    job = _make_job("repo", [], reason=reason)
    queue = [job_entry for job_entry in queue if job_entry.get("kind") != "repo"]
    queue = [job_entry for job_entry in queue if job_entry.get("kind") == "repo"]
    queue = [job]
    save_refresh_queue(root, queue)
    return job


def _changed_top_modules(paths: Iterable[str]) -> List[str]:
    modules = set()
    for path in paths:
        normalized = normalize_relative_path(path)
        if not normalized or normalized.startswith(".dotscope/"):
            continue
        parts = normalized.split("/")
        if parts and parts[0]:
            modules.add(parts[0])
    return sorted(modules)


def _find_scope_targets_for_files(root: str, changed_files: Iterable[str]) -> List[str]:
    from ..passes.incremental import _find_covering_scope
    from dotscope.engine.runtime_overlay import scope_name_from_logical_path

    targets = []
    seen = set()
    for path in changed_files:
        scope_path = _find_covering_scope(root, path)
        if not scope_path:
            continue
        name = scope_name_from_logical_path(scope_path)
        if name not in seen and not name.startswith("virtual/"):
            seen.add(name)
            targets.append(name)
    return sorted(targets)


def classify_refresh_job(
    root: str,
    changed_files: List[str],
    added_files: List[str],
    deleted_files: List[str],
    renamed: bool = False,
) -> Dict[str, object]:
    """Classify a commit into a scope refresh or repo refresh job."""
    marker = os.path.join(root, ".dotscope", "needs_full_ingest")
    state = load_incremental_state(root)

    if renamed or added_files or deleted_files:
        return _make_job("repo", [], reason="structural change")
    if os.path.exists(marker) or state.uncovered_new_files > 0:
        return _make_job("repo", [], reason="drift marker")
    if len(_changed_top_modules(changed_files)) > 3:
        return _make_job("repo", [], reason="multi-module change")

    targets = _find_scope_targets_for_files(root, changed_files)
    if targets:
        return _make_job("scope", targets, reason="impacted scopes")
    return _make_job("repo", [], reason="unclassified change")


def _get_commit_change_set(
    root: str, commit_hash: str,
) -> Tuple[List[str], List[str], List[str], bool, List[Tuple[str, str]]]:
    changed: List[str] = []
    added: List[str] = []
    deleted: List[str] = []
    renamed = False
    renames: List[Tuple[str, str]] = []

    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-status", "-r", commit_hash],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return changed, added, deleted, renamed, renames

    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0].strip()
        if status.startswith("R") and len(parts) >= 3:
            renamed = True
            old_path, new_path = parts[1].strip(), parts[2].strip()
            renames.append((old_path, new_path))
            changed.extend([old_path, new_path])
            continue

        path = parts[1].strip()
        changed.append(path)
        if status == "A":
            added.append(path)
        elif status == "D":
            deleted.append(path)

    return changed, added, deleted, renamed, renames


def patch_scope_paths_for_renames(
    root: str,
    renames: List[Tuple[str, str]],
) -> int:
    """Rewrite old paths to new paths in .scope files using text replacement.

    Only targets list item lines (``  - old/path``) under ``includes:`` and
    ``related:`` blocks.  Preserves inline comments and formatting.

    Also migrates keys in incremental_state.scope_refresh_timestamps.

    Returns the number of .scope files modified.
    """
    import re as _re
    from ..engine.discovery import find_all_scopes

    if not renames:
        return 0

    scope_files = find_all_scopes(root)
    patched_count = 0

    for scope_path in scope_files:
        try:
            with open(scope_path, "r", encoding="utf-8") as f:
                original = f.read()
        except (IOError, OSError):
            continue

        text = original
        for old_path, new_path in renames:
            escaped_old = _re.escape(old_path)
            pattern = r"(^\s*-\s+)" + escaped_old + r"(\s*(?:#.*)?)$"
            replacement = r"\g<1>" + new_path + r"\g<2>"
            text = _re.sub(pattern, replacement, text, flags=_re.MULTILINE)

        if text != original:
            try:
                with open(scope_path, "w", encoding="utf-8") as f:
                    f.write(text)
                patched_count += 1
            except (IOError, OSError):
                continue

    _migrate_incremental_keys(root, renames)
    return patched_count


def _migrate_incremental_keys(
    root: str,
    renames: List[Tuple[str, str]],
) -> None:
    """Migrate scope_refresh_timestamps keys for renamed paths."""
    state = load_incremental_state(root)
    timestamps = state.scope_refresh_timestamps
    if not timestamps:
        return

    changed = False
    for old_path, new_path in renames:
        old_key = scope_storage_key(old_path, root=root)
        if old_key in timestamps:
            new_key = scope_storage_key(new_path, root=root)
            timestamps[new_key] = timestamps.pop(old_key)
            changed = True

    if changed:
        save_incremental_state(root, state)


def enqueue_commit_refresh(root: str, commit_hash: str) -> Optional[Dict[str, object]]:
    """Classify a commit and enqueue the appropriate refresh work."""
    changed, added, deleted, renamed, renames = _get_commit_change_set(root, commit_hash)
    if not changed:
        return None

    # Proactively patch scope files before enqueuing rebuild
    if renames:
        patch_scope_paths_for_renames(root, renames)

    job = classify_refresh_job(root, changed, added, deleted, renamed=renamed)
    if job["kind"] == "repo":
        return enqueue_repo_refresh(root, reason=str(job.get("reason", "")))
    return enqueue_scope_refresh(root, job.get("targets", []), reason=str(job.get("reason", "")))


def run_scope_refresh(root: str, targets: Iterable[str], quiet: bool = True) -> bool:
    """Refresh one or more directory scopes into the runtime overlay."""
    from ..passes.lazy import lazy_ingest_module

    refreshed_paths = []
    for target in _normalize_targets(targets):
        if target.startswith("virtual/"):
            continue
        config = lazy_ingest_module(
            root,
            target,
            quiet=quiet,
            write_runtime=True,
            write_tracked=False,
            mark_needs_full_ingest=False,
        )
        if config is not None:
            refreshed_paths.append(config.path)

    if not refreshed_paths:
        return False

    state = load_incremental_state(root)
    mark_scopes_refreshed(root, state, refreshed_paths)
    save_incremental_state(root, state)
    return True


def run_repo_refresh(root: str, quiet: bool = True) -> bool:
    """Rebuild the full runtime overlay without touching tracked scope files."""
    from ..storage.cache import cache_ingest_data
    from ..workflows.ingest import _cache_invariants, ingest
    from ..engine.discovery import find_all_scopes
    from ..engine.runtime_overlay import sync_runtime_overlay, write_runtime_scope

    plan = ingest(
        root,
        dry_run=True,
        quiet=quiet,
        respect_existing_scopes=True,
    )
    tracked_scope_paths = find_all_scopes(root)
    if tracked_scope_paths:
        sync_runtime_overlay(root)
        for planned in plan.scopes:
            write_runtime_scope(root, planned.config)
    else:
        replace_runtime_overlay(
            root,
            [planned.config for planned in plan.scopes],
            index=plan.index,
        )
    cache_ingest_data(root, history=plan.history, graph=plan.graph)
    _cache_invariants(root, plan.history)
    reset_incremental_state(
        root,
        scope_paths=list(tracked_scope_paths) + [planned.config.path for planned in plan.scopes],
    )

    marker = os.path.join(root, ".dotscope", "needs_full_ingest")
    if os.path.exists(marker):
        os.remove(marker)
    return True


def _acquire_refresh_lock(root: str) -> Optional[int]:
    _ensure_dot_dir(root)
    path = refresh_lock_path(root)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    os.write(fd, str(os.getpid()).encode("utf-8"))
    return fd


def _release_refresh_lock(root: str, fd: Optional[int]) -> None:
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        os.remove(refresh_lock_path(root))
    except OSError:
        pass


def run_refresh_queue(root: str, drain: bool = False) -> bool:
    """Run queued refresh work. Returns True if a job ran."""
    lock_fd = _acquire_refresh_lock(root)
    if lock_fd is None:
        return False

    ran_job = False
    status = load_refresh_status(root)
    try:
        while True:
            queue = load_refresh_queue(root)
            if not queue:
                break

            job = queue.pop(0)
            save_refresh_queue(root, queue)
            status.update({
                "running": True,
                "current_job": job.get("kind"),
                "current_targets": job.get("targets", []),
            })
            save_refresh_status(root, status)

            try:
                if job.get("kind") == "repo":
                    run_repo_refresh(root, quiet=True)
                else:
                    run_scope_refresh(root, job.get("targets", []), quiet=True)

                status.update({
                    "last_success_at": utc_now_iso(),
                    "last_job_kind": job.get("kind"),
                    "last_targets": job.get("targets", []),
                    "last_error": "",
                })
            except Exception as exc:
                status.update({
                    "last_error_at": utc_now_iso(),
                    "last_error": str(exc),
                    "last_job_kind": job.get("kind"),
                    "last_targets": job.get("targets", []),
                })
                save_refresh_status(root, status)
                raise
            finally:
                status.update({
                    "running": False,
                    "current_job": None,
                    "current_targets": [],
                })
                save_refresh_status(root, status)

            ran_job = True
            if not drain:
                break
    finally:
        _release_refresh_lock(root, lock_fd)

    return ran_job


def kick_refresh_worker(root: str) -> None:
    """Spawn a detached worker to drain the refresh queue."""
    if not load_refresh_queue(root):
        return

    # NOTE: Intentionally fire-and-forget — worker self-terminates via queue drain.
    # Popen does not support timeout=; the child process exits once the queue is empty.
    subprocess.Popen(
        [sys.executable, "-m", "dotscope.cli", "refresh", "run", "--drain"],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def refresh_status_summary(root: str) -> Dict[str, object]:
    """Return the current queue + worker status."""
    status = load_refresh_status(root)
    queue = load_refresh_queue(root)
    summary = dict(status)
    summary["queued_job_count"] = len(queue)
    summary["queued_jobs"] = queue
    return summary


def run_refresh_inline(
    root: str,
    targets: Optional[List[str]] = None,
    repo: bool = False,
    quiet: bool = False,
) -> Dict[str, object]:
    """Run a refresh synchronously: enqueue, drain, return results.

    This is the simple "just do it" entry point.  Enqueues the appropriate job
    and drains the queue inline (no subprocess worker).

    Returns dict with {success, kind, targets_refreshed, duration_ms, error}.
    """
    t0 = time.time()

    if repo:
        enqueue_repo_refresh(root, reason="inline")
    elif targets:
        job = enqueue_scope_refresh(root, targets, reason="inline")
        if job is None:
            return {
                "success": False,
                "kind": "scope",
                "targets_refreshed": [],
                "duration_ms": 0,
                "error": "Could not enqueue (repo refresh already pending or running)",
            }
    else:
        enqueue_repo_refresh(root, reason="inline-default")

    try:
        ran = run_refresh_queue(root, drain=True)
    except Exception as exc:
        elapsed = int((time.time() - t0) * 1000)
        return {
            "success": False,
            "kind": "repo" if repo or not targets else "scope",
            "targets_refreshed": targets or [],
            "duration_ms": elapsed,
            "error": str(exc),
        }

    elapsed = int((time.time() - t0) * 1000)
    status = load_refresh_status(root)
    return {
        "success": ran and not status.get("last_error"),
        "kind": status.get("last_job_kind", "repo" if repo or not targets else "scope"),
        "targets_refreshed": status.get("last_targets", targets or []),
        "duration_ms": elapsed,
        "error": status.get("last_error", ""),
    }


def _repo_job_pending_or_running(root: str) -> bool:
    status = load_refresh_status(root)
    if status.get("running") and status.get("current_job") == "repo":
        return True
    return any(job.get("kind") == "repo" for job in load_refresh_queue(root))


def _wait_for_repo_refresh(root: str, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not _repo_job_pending_or_running(root):
            return True
        time.sleep(0.05)
    return not _repo_job_pending_or_running(root)


def _refresh_timestamp_string(root: str, config_path: str) -> str:
    state = load_incremental_state(root)
    return str(state.scope_refresh_timestamps.get(scope_storage_key(config_path, root=root), ""))


def ensure_resolution_freshness(
    root: str,
    scope_expr: str,
    timeout_seconds: float = REFRESH_WAIT_SECONDS,
) -> Dict[str, object]:
    """Attempt to self-heal stale or missing scopes before resolution."""
    from ..engine.composer import parse_expression
    from ..ux.health import check_staleness

    try:
        refs = [op.ref.name for op in parse_expression(scope_expr)]
    except ValueError:
        refs = [scope_expr]

    unique_refs = []
    seen = set()
    for ref in refs:
        normalized = normalize_relative_path(ref).rstrip("/")
        if normalized and normalized not in seen:
            unique_refs.append(normalized)
            seen.add(normalized)

    primary_ref = unique_refs[0] if unique_refs else normalize_relative_path(scope_expr).rstrip("/")
    stale_scope_targets = []
    needs_repo = False
    healed = False
    job_kind = None

    state = load_incremental_state(root)

    for ref in unique_refs:
        config, _source = find_effective_scope_with_source(ref, root=root)
        if config is None:
            if ref.startswith("virtual/"):
                needs_repo = True
            else:
                stale_scope_targets.append(ref)
            continue

        if ref.startswith("virtual/"):
            if check_staleness(config, root, state=state):
                needs_repo = True
            continue

        if check_staleness(config, root, state=state):
            stale_scope_targets.append(ref)

    if stale_scope_targets and not needs_repo:
        started = time.time()
        for target in _normalize_targets(stale_scope_targets):
            if time.time() - started >= timeout_seconds:
                break
            if run_scope_refresh(root, [target], quiet=True):
                healed = True
                job_kind = "scope"

        refreshed_state = load_incremental_state(root)
        remaining = []
        for target in stale_scope_targets:
            config, _source = find_effective_scope_with_source(target, root=root)
            if config is None or check_staleness(config, root, state=refreshed_state):
                remaining.append(target)
        stale_scope_targets = remaining

    if needs_repo:
        job_kind = "repo"
        enqueue_repo_refresh(root, reason=f"resolve:{scope_expr}")
        kick_refresh_worker(root)
        if _wait_for_repo_refresh(root, timeout_seconds):
            healed = True
            needs_repo = False

    if stale_scope_targets:
        enqueue_scope_refresh(root, stale_scope_targets, reason=f"resolve:{scope_expr}")
        kick_refresh_worker(root)

    config, source = find_effective_scope_with_source(primary_ref or scope_expr, root=root)
    state_value = "fresh"
    if healed and job_kind:
        state_value = "self_healed"
    elif needs_repo:
        state_value = "stale_fallback"
    elif stale_scope_targets:
        state_value = "stale_git_drift"

    last_refreshed = ""
    if config is not None:
        last_refreshed = _refresh_timestamp_string(root, config.path)

    return {
        "state": state_value,
        "source": source or "tracked_snapshot",
        "last_refreshed": last_refreshed,
        "healed": healed,
        "job_kind": job_kind,
    }
