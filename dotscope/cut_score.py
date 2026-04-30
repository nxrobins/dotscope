"""Score closed bug-fix PRs against the live-trial within-repo task criteria.

Pure logic module: GitHub API fetching, classification, aggregation. CLI lives
in `dotscope/cli/cut_score.py`.

Public corpus eligibility narrows to PRs with `regression_test_status == "modified"`
per pre-registration deviation `regression_test_modified_only`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


CUT_SCORE_VERSION = "1.0"
MIN_FILES = 3
MIN_MODULES = 2
LOC_HARD_GATE = 800
LOC_SOFT_GATE = 400
QUALIFYING_RATE_GATE = 0.60
DEFAULT_LABEL = "bug"
DEFAULT_PER_PAGE = 30
PRIMARY_REPOS = ("sqlalchemy/sqlalchemy", "pydantic/pydantic", "pytest-dev/pytest")
FALLBACK_REPOS = ("django/django", "celery/celery")


class CutScoreError(ValueError):
    """Raised when cut-score input is invalid or fetching fails irrecoverably."""


@dataclass
class CutScoreRow:
    repo: str
    pr: int
    title: str
    closed_at: str
    files_changed: int
    modules: List[str]
    regression_test_status: str  # "modified" | "added" | "absent"
    loc_total: int
    candidate_test_paths: List[str]
    qualifies_public: Optional[bool]
    qualifies_diagnostic: Optional[bool]
    reasons: List[str] = field(default_factory=list)
    proxies: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Path / module / test classification
# ---------------------------------------------------------------------------

_TEST_PATH_HINTS = ("/test_", "/tests/", "/testing/", "test_", "_test.py")


def is_test_path(path: str) -> bool:
    p = path.replace("\\", "/").lower()
    if p.startswith("tests/") or p.startswith("testing/"):
        return True
    name = p.rsplit("/", 1)[-1]
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    return any(hint in p for hint in _TEST_PATH_HINTS)


_MODIFIED_STATUSES = {"modified", "renamed", "changed"}


def regression_test_classification(files: List[Dict[str, Any]]) -> str:
    """Classify the regression-test treatment in a PR based on file statuses.

    Returns "modified" if any test file existed at parent and was changed.
    Returns "added" if no modified test exists but new tests were added.
    Returns "absent" if no test files appear in the diff.
    """
    test_files = [f for f in files if is_test_path(f.get("filename") or "")]
    if not test_files:
        return "absent"
    if any((f.get("status") or "") in _MODIFIED_STATUSES for f in test_files):
        return "modified"
    if any((f.get("status") or "") == "added" for f in test_files):
        return "added"
    # Fallback: any test file present at all (e.g., status "removed") still counts as touched
    return "absent"


def candidate_test_paths(
    files: List[Dict[str, Any]],
    regression_status: str,
) -> List[str]:
    """Return candidate test paths suitable as `pytest <path>` validation targets.

    For "modified" status, only returns paths whose status indicates the file
    existed at parent (so pytest can resolve them on the parent worktree).
    """
    paths: List[str] = []
    for f in files:
        filename = f.get("filename") or ""
        if not is_test_path(filename):
            continue
        status = f.get("status") or ""
        if regression_status == "modified" and status not in _MODIFIED_STATUSES:
            continue
        if regression_status == "added" and status != "added":
            continue
        paths.append(filename)
    return paths


def _module_at_depth(path: str, depth: int) -> str:
    """Return the path component at the given zero-indexed depth, falling back
    to the deepest available directory component if the file is shallower."""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if not parts:
        return ""
    # File component is parts[-1]; directory components are parts[:-1].
    if depth < len(parts) - 1:
        return parts[depth]
    # If file is shallower than requested depth, return the closest
    # directory component (which may be parts[0] if file is top-level).
    return parts[max(0, len(parts) - 2)]


def _module_top_pkg(path: str) -> str:
    return _module_at_depth(path, 0)


def _module_depth_2(path: str) -> str:
    return _module_at_depth(path, 1)


def _module_depth_3(path: str) -> str:
    return _module_at_depth(path, 2)


def _module_leaf_dir(path: str) -> str:
    """Innermost directory containing the file. For top-level files,
    falls back to the package root."""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


MODULE_EXTRACTORS: Dict[str, Callable[[str], str]] = {
    "top-pkg": _module_top_pkg,
    "depth-2": _module_depth_2,
    "depth-3": _module_depth_3,
    "leaf-dir": _module_leaf_dir,
}


# Recommended starting points per pre-reg primary repo. Operators can override
# via --module-style-override. These are not gospel; verify with --module-style
# probing on a small sample first.
RECOMMENDED_MODULE_STYLE: Dict[str, str] = {
    "sqlalchemy/sqlalchemy": "depth-3",   # lib/sqlalchemy/<module>/...
    "pytest-dev/pytest": "depth-2",       # src/_pytest/... or testing/...
    "pydantic/pydantic": "top-pkg",       # pydantic/... + tests/... at top
    # Fallback repos:
    "django/django": "depth-2",           # django/<module>/...
    "celery/celery": "top-pkg",           # celery/... at top
}


def count_modules(files: List[Dict[str, Any]], extractor: Callable[[str], str]) -> List[str]:
    seen: List[str] = []
    for f in files:
        filename = f.get("filename") or ""
        module = extractor(filename)
        if module and module not in seen:
            seen.append(module)
    return seen


def loc_proxy(files: List[Dict[str, Any]]) -> int:
    return sum(int(f.get("additions") or 0) + int(f.get("deletions") or 0) for f in files)


# ---------------------------------------------------------------------------
# Per-PR scoring
# ---------------------------------------------------------------------------

def score_pr(
    pr: Dict[str, Any],
    files: List[Dict[str, Any]],
    module_extractor: Callable[[str], str],
    repo: str,
) -> CutScoreRow:
    files_changed = len(files)
    modules = count_modules(files, module_extractor)
    regression_status = regression_test_classification(files)
    loc = loc_proxy(files)
    test_paths = candidate_test_paths(files, regression_status)

    reasons: List[str] = []
    if files_changed < MIN_FILES:
        reasons.append(f"files_changed {files_changed} < {MIN_FILES}")
    if len(modules) < MIN_MODULES:
        reasons.append(f"modules {len(modules)} < {MIN_MODULES}")
    if regression_status == "absent":
        reasons.append("no regression test in diff")
    if loc > LOC_HARD_GATE:
        reasons.append(f"loc {loc} > hard gate {LOC_HARD_GATE}")

    mechanically_qualifies = not reasons

    # Public eligibility narrows to "modified" regression tests (Deviation 1).
    qualifies_public: Optional[bool]
    if not mechanically_qualifies:
        qualifies_public = False
    elif regression_status != "modified":
        qualifies_public = False
        reasons.append(
            "public corpus requires regression_test_status=='modified' (Deviation 1)"
        )
    elif loc > LOC_SOFT_GATE:
        qualifies_public = None  # soft band — operator gating
    else:
        qualifies_public = True

    qualifies_diagnostic: Optional[bool]
    if not mechanically_qualifies:
        qualifies_diagnostic = False
    elif loc > LOC_SOFT_GATE:
        qualifies_diagnostic = None
    else:
        qualifies_diagnostic = True

    proxies = {
        "loc_soft_gate": LOC_SOFT_GATE,
        "loc_hard_gate": LOC_HARD_GATE,
        "in_loc_soft_band": LOC_SOFT_GATE < loc <= LOC_HARD_GATE,
    }

    return CutScoreRow(
        repo=repo,
        pr=int(pr.get("number") or 0),
        title=pr.get("title") or "",
        closed_at=pr.get("closed_at") or "",
        files_changed=files_changed,
        modules=modules,
        regression_test_status=regression_status,
        loc_total=loc,
        candidate_test_paths=test_paths,
        qualifies_public=qualifies_public,
        qualifies_diagnostic=qualifies_diagnostic,
        reasons=reasons,
        proxies=proxies,
    )


def aggregate_repo(rows: List[CutScoreRow], repo: str) -> Dict[str, Any]:
    n = len(rows)
    public_yes = sum(1 for r in rows if r.qualifies_public is True)
    diag_yes = sum(1 for r in rows if r.qualifies_diagnostic is True)
    public_rate = (public_yes / n) if n else 0.0
    diag_rate = (diag_yes / n) if n else 0.0
    gate_passed = public_rate >= QUALIFYING_RATE_GATE
    fallback = None
    if not gate_passed:
        fallback = (
            "Pre-reg line 43 fallbacks: Django subsystem-scoped or Celery. "
            "Operator decision required."
        )
    return {
        "repo": repo,
        "n_examined": n,
        "qualifying_public": public_yes,
        "qualifying_diagnostic": diag_yes,
        "qualifying_rate_public": round(public_rate, 4),
        "qualifying_rate_diagnostic": round(diag_rate, 4),
        "gate_threshold": QUALIFYING_RATE_GATE,
        "gate_passed": gate_passed,
        "fallback_recommendation": fallback,
    }


# ---------------------------------------------------------------------------
# GitHub fetching
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"


def _make_client(token: Optional[str]):
    try:
        import httpx  # type: ignore[import-not-found]
    except ImportError as exc:
        raise CutScoreError(
            "httpx is required for cut-score. Install with: pip install dotscope[cut-score]"
        ) from exc
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "dotscope-cut-score/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=GITHUB_API, headers=headers, timeout=30.0)


def fetch_closed_bugfix_prs(
    client: Any,
    owner_repo: str,
    n: int,
    label: str = DEFAULT_LABEL,
) -> List[Dict[str, Any]]:
    """Fetch up to `n` most recent closed merged bug-fix PRs for a repo."""
    rows: List[Dict[str, Any]] = []
    page = 1
    label_token = label if " " not in label and ":" not in label else f'"{label}"'
    query = f"repo:{owner_repo} is:pr is:closed is:merged label:{label_token}"
    while len(rows) < n:
        per_page = min(DEFAULT_PER_PAGE, n - len(rows))
        params = {
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": per_page,
            "page": page,
        }
        response = client.get("/search/issues", params=params)
        if response.status_code == 422:
            raise CutScoreError(
                f"GitHub search rejected query for {owner_repo}: {response.text[:200]}"
            )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items") or []
        if not items:
            break
        rows.extend(items)
        if len(items) < per_page:
            break
        page += 1
    return rows[:n]


def fetch_pr_files(client: Any, owner_repo: str, pr_number: int) -> List[Dict[str, Any]]:
    """Fetch all changed files in a PR (paginated, up to 3000)."""
    files: List[Dict[str, Any]] = []
    page = 1
    while True:
        params = {"per_page": 100, "page": page}
        response = client.get(f"/repos/{owner_repo}/pulls/{pr_number}/files", params=params)
        response.raise_for_status()
        page_files = response.json() or []
        if not page_files:
            break
        files.extend(page_files)
        if len(page_files) < 100:
            break
        page += 1
        if page > 30:  # safety
            break
    return files


def score_repo(
    client: Any,
    owner_repo: str,
    n: int,
    label: str = DEFAULT_LABEL,
    module_style: str = "top-pkg",
) -> Tuple[List[CutScoreRow], Dict[str, Any]]:
    """Pull closed bug-fix PRs for a repo and score each."""
    extractor = MODULE_EXTRACTORS.get(module_style)
    if extractor is None:
        raise CutScoreError(
            f"unknown module_style: {module_style!r}. "
            f"Use one of: {sorted(MODULE_EXTRACTORS)}"
        )
    prs = fetch_closed_bugfix_prs(client, owner_repo, n, label=label)
    rows: List[CutScoreRow] = []
    for pr in prs:
        files = fetch_pr_files(client, owner_repo, int(pr["number"]))
        rows.append(score_pr(pr, files, extractor, owner_repo))
    summary = aggregate_repo(rows, owner_repo)
    # Heuristic warning: every PR ended up with one module under top-pkg
    if module_style == "top-pkg" and rows:
        if all(len(r.modules) <= 1 for r in rows):
            summary["module_style_warning"] = (
                "All PRs scored as <=1 module under top-pkg; "
                "consider --module-style depth-2 for nested layouts"
            )
    return rows, summary


def rows_to_jsonable(rows: Iterable[CutScoreRow]) -> List[Dict[str, Any]]:
    return [asdict(row) for row in rows]


def _parse_kv_pairs(items: List[str], flag_name: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise CutScoreError(f"{flag_name} expects REPO=VALUE, got: {item!r}")
        repo, _, value = item.partition("=")
        if not repo or not value:
            raise CutScoreError(f"{flag_name} has empty repo or value: {item!r}")
        out[repo] = value
    return out


def parse_label_overrides(items: List[str]) -> Dict[str, str]:
    return _parse_kv_pairs(items, "--label-override")


def parse_module_style_overrides(items: List[str]) -> Dict[str, str]:
    overrides = _parse_kv_pairs(items, "--module-style-override")
    for repo, style in overrides.items():
        if style not in MODULE_EXTRACTORS:
            raise CutScoreError(
                f"unknown module style {style!r} for {repo!r}. "
                f"Use one of: {sorted(MODULE_EXTRACTORS)}"
            )
    return overrides


def resolve_module_style(repo: str, default: str, overrides: Dict[str, str]) -> str:
    if repo in overrides:
        return overrides[repo]
    if repo in RECOMMENDED_MODULE_STYLE:
        return RECOMMENDED_MODULE_STYLE[repo]
    return default


def run_cut_score(
    repos: List[str],
    n: int,
    token: Optional[str],
    label_overrides: Dict[str, str],
    default_module_style: str,
    module_style_overrides: Optional[Dict[str, str]] = None,
    client: Any = None,
) -> Dict[str, Any]:
    """Score each repo and produce a combined report payload.

    `client` may be supplied for testing; otherwise a fresh httpx client is built.
    """
    module_style_overrides = module_style_overrides or {}
    owns_client = client is None
    if owns_client:
        client = _make_client(token)

    try:
        per_repo: List[Dict[str, Any]] = []
        any_failed = False
        for repo in repos:
            label = label_overrides.get(repo, DEFAULT_LABEL)
            module_style = resolve_module_style(
                repo, default_module_style, module_style_overrides
            )
            rows, summary = score_repo(
                client,
                repo,
                n=n,
                label=label,
                module_style=module_style,
            )
            per_repo.append({
                "summary": summary,
                "rows": rows_to_jsonable(rows),
                "label_used": label,
                "module_style_used": module_style,
                "module_style_source": (
                    "override" if repo in module_style_overrides
                    else "recommended" if repo in RECOMMENDED_MODULE_STYLE
                    else "default"
                ),
            })
            if not summary["gate_passed"]:
                any_failed = True
    finally:
        if owns_client:
            client.close()

    return {
        "schema_version": 1,
        "cut_score_version": CUT_SCORE_VERSION,
        "n_per_repo": n,
        "default_module_style": default_module_style,
        "any_repo_failed_gate": any_failed,
        "repos": per_repo,
    }


def write_report(payload: Dict[str, Any], out_path: Optional[str]) -> Optional[str]:
    if not out_path:
        return None
    from .storage.atomic import atomic_write_json
    atomic_write_json(out_path, payload)
    return out_path
