"""Generated Artifacts data models."""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class GeneratedArtifact:
    """Output of a single artifact renderer."""
    name: str               # "architecture_contracts", "network_map", "co_change_atlas"
    content: str            # Rendered markdown
    file_name: str          # "ARCHITECTURE_CONTRACTS.md"
    data_sources: List[str] = field(default_factory=list)  # Cache files read
    stats: Dict[str, int] = field(default_factory=dict)    # {"scopes": 5, "contracts": 23}


@dataclass
class GenerateConfig:
    """Configuration for artifact generation."""
    output_dir: str = "docs/dotscope"
    artifacts: List[str] = field(default_factory=lambda: [
        "architecture_contracts", "network_map", "co_change_atlas"
    ])
    ghost_coupling_threshold: float = 0.6
    hub_threshold_pct: int = 10
    stability_window_days: int = 30
    include_empty_scopes: bool = False
