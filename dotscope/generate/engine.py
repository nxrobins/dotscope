"""Artifact generation engine: load cache, call renderers, write files.

Deterministic output: given the same cache state, produces byte-identical
artifacts. Header timestamp derived from commit hash, not wall clock.
"""

import os
import subprocess
from pathlib import Path
from typing import List, Optional

from .models import GenerateConfig, GeneratedArtifact


# Stale cache threshold (same as Pillar 5)
STALE_COMMIT_THRESHOLD = 50


def generate(
    root: str,
    config: Optional[GenerateConfig] = None,
    artifact_filter: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
) -> List[GeneratedArtifact]:
    """Generate all configured artifacts.

    Args:
        root: Repository root.
        config: Generation config (defaults applied if None).
        artifact_filter: Only generate this artifact ("contracts", "network", "atlas").
        dry_run: Print to stdout, don't write files.
        force: Override stale cache guard.

    Returns:
        List of generated artifacts.
    """
    if config is None:
        config = _load_config(root)

    # Check cache existence
    cache_dir = Path(root) / ".dotscope"
    if not cache_dir.exists():
        raise SystemExit("No .dotscope/ directory found. Run `dotscope ingest` first.")

    # Check staleness
    stale_warning = ""
    if not force:
        is_stale, gap = _check_staleness(root)
        if is_stale:
            stale_warning = (
                f"> **WARNING: Generated from stale cache ({gap} commits behind HEAD).** "
                f"Run `dotscope ingest` to refresh.\n\n"
            )

    # Get deterministic timestamp from cache commit
    header_timestamp = _get_cache_timestamp(root)
    header_commit = _get_cache_commit(root)

    # Dispatch to renderers
    artifacts = []
    name_map = {
        "contracts": "architecture_contracts",
        "network": "network_map",
        "atlas": "co_change_atlas",
        "architecture_contracts": "architecture_contracts",
        "network_map": "network_map",
        "co_change_atlas": "co_change_atlas",
    }

    requested = config.artifacts
    if artifact_filter:
        canonical = name_map.get(artifact_filter, artifact_filter)
        requested = [canonical]

    for artifact_name in requested:
        try:
            if artifact_name == "architecture_contracts":
                from .contracts import render_contracts
                art = render_contracts(root, config, header_timestamp, header_commit)
            elif artifact_name == "network_map":
                from .network import render_network_map
                art = render_network_map(root, config, header_timestamp, header_commit)
            elif artifact_name == "co_change_atlas":
                from .atlas import render_atlas
                art = render_atlas(root, config, header_timestamp, header_commit)
            else:
                continue

            # Inject stale warning if needed
            if stale_warning and art.content:
                lines = art.content.split("\n", 2)
                if len(lines) >= 2:
                    art.content = lines[0] + "\n\n" + stale_warning + "\n".join(lines[1:])

            artifacts.append(art)
        except Exception:
            continue

    # Write or print
    if dry_run:
        for art in artifacts:
            print(f"--- {art.file_name} ---")
            print(art.content)
    else:
        output_dir = Path(root) / config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        for art in artifacts:
            (output_dir / art.file_name).write_text(art.content, encoding="utf-8")

    return artifacts


def _load_config(root: str) -> GenerateConfig:
    """Load generate config from .dotscope/config.yaml or return defaults."""
    config_path = Path(root) / ".dotscope" / "config.yaml"
    if not config_path.exists():
        return GenerateConfig()

    try:
        from ..parser import _parse_yaml
        data = _parse_yaml(config_path.read_text(encoding="utf-8"))
        gen = data.get("generate", {})
        return GenerateConfig(
            output_dir=gen.get("output_dir", "docs/dotscope"),
            artifacts=gen.get("artifacts", GenerateConfig.artifacts),
            ghost_coupling_threshold=gen.get("ghost_coupling_threshold", 0.6),
            hub_threshold_pct=gen.get("hub_threshold_pct", 10),
            stability_window_days=gen.get("stability_window_days", 30),
            include_empty_scopes=gen.get("include_empty_scopes", False),
        )
    except Exception:
        return GenerateConfig()


def _check_staleness(root: str) -> tuple:
    """Check if cache is stale. Returns (is_stale, commit_gap)."""
    try:
        from ..search.retriever import check_index_freshness
        is_fresh, msg = check_index_freshness(root)
        if not is_fresh and "commits" in msg:
            # Extract gap count from message
            import re
            match = re.search(r"(\d+) commits", msg)
            if match:
                return True, int(match.group(1))
        return not is_fresh, 0
    except Exception:
        return False, 0


def _get_cache_timestamp(root: str) -> str:
    """Get timestamp from the cache's commit (deterministic)."""
    commit = _get_cache_commit(root)
    if not commit:
        return "unknown"
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%cI", commit],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            # Trim to date only for readability
            return result.stdout.strip()[:10]
    except Exception:
        pass
    return "unknown"


def _get_cache_commit(root: str) -> str:
    """Get the commit hash the cache was built against."""
    import json
    index_path = Path(root) / ".dotscope" / "cache" / "vector_index.json"
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            commit = data.get("last_vector_update_commit", "")
            return commit[:7] if commit else ""
        except Exception:
            pass
    # Fallback to current HEAD
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""
