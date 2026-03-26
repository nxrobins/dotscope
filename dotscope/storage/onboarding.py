"""Stage-aware onboarding: guide the developer from skepticism to dependency.

Tracks milestones in .dotscope/onboarding.json. Used to:
1. Tailor "next step" prompts (one at a time, never nag)
2. Gate complexity (counterfactuals after 3+ observations, health after 7+ days)
3. Celebrate milestones (first session, first observation, first counterfactual)
"""

import json
import os
import time
from typing import Optional


def load_onboarding(repo_root: str) -> dict:
    """Load onboarding state, creating default if missing."""
    path = _onboarding_path(repo_root)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return _default_state()


def save_onboarding(repo_root: str, state: dict) -> None:
    """Persist onboarding state."""
    dot_dir = os.path.join(repo_root, ".dotscope")
    os.makedirs(dot_dir, exist_ok=True)
    path = _onboarding_path(repo_root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def mark_milestone(repo_root: str, milestone: str) -> dict:
    """Record a milestone timestamp if not already set."""
    state = load_onboarding(repo_root)
    if milestone in state and state[milestone] is None:
        state[milestone] = _now()
        save_onboarding(repo_root, state)
    return state


def increment_counter(repo_root: str, counter: str) -> dict:
    """Increment a counter (sessions_completed, observations_recorded)."""
    state = load_onboarding(repo_root)
    state[counter] = state.get(counter, 0) + 1
    save_onboarding(repo_root, state)
    return state


# ---------------------------------------------------------------------------
# Gating rules: when to show what
# ---------------------------------------------------------------------------

def should_show_counterfactuals(state: dict) -> bool:
    """Counterfactuals need observation data to be meaningful."""
    return state.get("observations_recorded", 0) >= 3


def should_show_health_nudges(state: dict) -> bool:
    """Health nudges aren't relevant on day 1."""
    first = state.get("first_ingest")
    if not first:
        return False
    try:
        elapsed = time.time() - _parse_ts(first)
        return elapsed >= 7 * 86400  # 7 days
    except (ValueError, TypeError):
        return True  # If we can't parse, show them


def next_step(state: dict) -> Optional[str]:
    """Return the single next action the developer should take, or None."""
    if not state.get("first_backtest"):
        return "Next: `dotscope check --backtest`"
    if not state.get("conventions_reviewed"):
        return "Next: `dotscope conventions`"
    if not state.get("voice_reviewed"):
        return "Next: `dotscope voice`"
    if not state.get("first_session"):
        return "Next: Add dotscope to your agent (docs/mcp-setup.md)"
    if not state.get("hook_installed"):
        return "Next: `dotscope hook install`"
    return None  # Onboarded. Stop prompting.


def milestone_message(state: dict) -> Optional[str]:
    """Return a milestone celebration message, or None."""
    sessions = state.get("sessions_completed", 0)
    observations = state.get("observations_recorded", 0)

    if sessions == 1:
        return "First session tracked."
    if observations == 1:
        return "Feedback loop active — scopes will improve with use."
    if sessions == 5:
        return f"5 sessions completed. {observations} observations recorded."
    return None


def version_control_tip(state: dict) -> Optional[str]:
    """One-time tip about committing .scope files. Shown on first ingest only."""
    if state.get("vc_tip_shown"):
        return None
    return (
        "Commit .scope files and intent.yaml. .dotscope/ is gitignored and rebuilds."
    )


def mark_vc_tip_shown(repo_root: str) -> None:
    """Record that the version control tip has been shown."""
    state = load_onboarding(repo_root)
    state["vc_tip_shown"] = True
    save_onboarding(repo_root, state)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _onboarding_path(repo_root: str) -> str:
    return os.path.join(repo_root, ".dotscope", "onboarding.json")


def _default_state() -> dict:
    return {
        "first_ingest": None,
        "first_backtest": None,
        "first_session": None,
        "hook_installed": None,
        "first_observation": None,
        "first_check_hold": None,
        "conventions_reviewed": None,
        "voice_reviewed": None,
        "sessions_completed": 0,
        "observations_recorded": 0,
        "vc_tip_shown": False,
    }


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_ts(ts: str) -> float:
    """Parse ISO timestamp to epoch seconds."""
    from datetime import datetime as dt
    return dt.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
