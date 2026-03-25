"""Cache structured ingest data to .dotscope/ for MCP server consumption.

Serializes HistoryAnalysis and DependencyGraph to JSON after ingest.
MCP server loads them on startup for attribution hints and near-miss detection.
"""

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .graph import DependencyGraph, FileNode, ModuleBoundary
from .history import (
    HistoryAnalysis, FileHistory, ChangeCoupling, ImplicitContract,
)


def cache_ingest_data(
    root: str,
    history: Optional[HistoryAnalysis] = None,
    graph: Optional[DependencyGraph] = None,
) -> None:
    """Cache history and graph to .dotscope/ after ingest."""
    dot_dir = Path(root) / ".dotscope"
    dot_dir.mkdir(exist_ok=True)

    if history and history.commits_analyzed > 0:
        data = {
            "commits_analyzed": history.commits_analyzed,
            "implicit_contracts": [
                {
                    "trigger_file": ic.trigger_file,
                    "coupled_file": ic.coupled_file,
                    "confidence": ic.confidence,
                    "occurrences": ic.occurrences,
                    "description": ic.description,
                }
                for ic in history.implicit_contracts
            ],
            "hotspots": history.hotspots[:20],
            "file_stabilities": {
                path: {"stability": fh.stability, "commit_count": fh.commit_count}
                for path, fh in history.file_histories.items()
                if fh.stability
            },
        }
        with open(dot_dir / "history.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    if graph and graph.files:
        # Only cache what attribution hints need: imported_by fan-in
        hubs = {}
        for path, node in graph.files.items():
            if len(node.imported_by) >= 3:
                hubs[path] = {
                    "imported_by_count": len(node.imported_by),
                    "imported_by_dirs": sorted(set(
                        str(Path(p).parts[0]) for p in node.imported_by
                        if "/" in p
                    )),
                }
        if hubs:
            with open(dot_dir / "graph_hubs.json", "w", encoding="utf-8") as f:
                json.dump(hubs, f, indent=2)


def load_cached_history(root: str) -> Optional[HistoryAnalysis]:
    """Load cached history from .dotscope/history.json."""
    path = Path(root) / ".dotscope" / "history.json"
    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        history = HistoryAnalysis(
            commits_analyzed=data.get("commits_analyzed", 0),
        )
        for ic_data in data.get("implicit_contracts", []):
            history.implicit_contracts.append(ImplicitContract(
                trigger_file=ic_data["trigger_file"],
                coupled_file=ic_data["coupled_file"],
                confidence=ic_data["confidence"],
                occurrences=ic_data["occurrences"],
                description=ic_data.get("description", ""),
            ))
        for path_str, fh_data in data.get("file_stabilities", {}).items():
            history.file_histories[path_str] = FileHistory(
                path=path_str,
                stability=fh_data.get("stability", ""),
                commit_count=fh_data.get("commit_count", 0),
            )
        history.hotspots = data.get("hotspots", [])
        return history
    except (json.JSONDecodeError, KeyError):
        return None


def load_cached_graph_hubs(root: str) -> dict:
    """Load cached graph hub data from .dotscope/graph_hubs.json.

    Returns: {path: {"imported_by_count": int, "imported_by_dirs": [str]}}
    """
    path = Path(root) / ".dotscope" / "graph_hubs.json"
    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}
