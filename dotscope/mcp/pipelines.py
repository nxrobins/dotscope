import json
import os
import time as _time
from typing import Dict, Any, List, Optional
from .logger import get_mcp_logger

logger = get_mcp_logger()

class PipelineStage:
    """Base definition for an isolated execution layer inside the Resolve Pipeline."""
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Stages must implement process()")

class Pipeline:
    def __init__(self, stages: List[PipelineStage]):
        self.stages = stages

    def execute(self, initial_state: Dict[str, Any]) -> Dict[str, Any]:
        state = initial_state
        for stage in self.stages:
            stage_name = stage.__class__.__name__
            logger.debug(f"[Pipeline] Executing Stage: {stage_name}")
            try:
                state = stage.process(state)
            except Exception as e:
                logger.error(f"[Pipeline Stage Error] {stage_name} gracefully failed: {str(e)}", exc_info=True)
                # Fail-safes ensure minor enrichment exceptions don't cascade and crash primary telemetry output
                if hasattr(e, "to_dict"):
                    state["halt_error"] = json.dumps(e.to_dict(), indent=2)
                    break
        return state

class InitCompilationStage(PipelineStage):
    """Compiles the primary scope file array via composer limits and ensures freshness."""
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from ..engine.composer import compose, compose_for_task
        from ..workflows.refresh import ensure_resolution_freshness
        
        root = state["root"]
        scope = state["scope"]
        task = state["task"]
        follow_related = state.get("follow_related", True)

        state["freshness"] = ensure_resolution_freshness(root, scope) if root else {
            "state": "fresh",
            "source": "tracked_snapshot",
            "last_refreshed": "",
            "healed": False,
            "job_kind": None,
        }

        # Auto-compose from task when scope is a simple name and task is provided
        _is_simple_name = not any(c in scope for c in "+-&@")
        if task and _is_simple_name:
            resolved = compose_for_task(task, root=root, max_scopes=3)
            if not resolved.files:
                resolved = compose(scope, root=root, follow_related=follow_related)
        else:
            resolved = compose(scope, root=root, follow_related=follow_related)
        
        state["resolved"] = resolved
        return state

class EnrichmentStage(PipelineStage):
    """Injects fundamental architectural invariants and lessons (Wire 1)."""
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        root = state["root"]
        scope = state["scope"]
        resolved = state["resolved"]
        dot_dir = os.path.join(root, ".dotscope") if root else None
        
        if dot_dir and os.path.exists(dot_dir):
            from ..workflows.lessons import load_lessons, load_invariants, format_lessons_for_context
            module = scope.split("+")[0].split("-")[0].split("&")[0].split("@")[0]
            state["module"] = module
            
            lessons = load_lessons(dot_dir, module)
            invariants = load_invariants(dot_dir, module)
            enrichment = format_lessons_for_context(lessons, invariants)
            if enrichment:
                resolved.context = resolved.context + "\n\n" + enrichment
            
        return state

class BudgetExecutionStage(PipelineStage):
    """Retrieves file utility metrics and enforces hard MCP token boundaries (Wire 3)."""
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        root = state["root"]
        module = state.get("module")
        budget = state.get("budget")
        resolved = state["resolved"]
        dot_dir = os.path.join(root, ".dotscope") if root else None

        utility_scores = None
        if dot_dir and os.path.exists(dot_dir):
            from ..engine.utility import load_utility_scores
            utility_scores = load_utility_scores(dot_dir)

        required_files = None
        assertions = []
        if module:
            from ..engine.assertions import load_assertions, get_required_files
            assertions = load_assertions(root, module)
            required_files = get_required_files(assertions, module) or None
            state["assertions"] = assertions

        if budget is not None:
            from ..passes.budget_allocator import apply_budget
            state["resolved"] = apply_budget(resolved, budget, utility_scores=utility_scores, required_files=required_files)

        return state

class TrackerStage(PipelineStage):
    """Instantiates physical database execution logs marking standard milestones."""
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        root = state["root"]
        scope = state["scope"]
        budget = state.get("budget")
        resolved = state["resolved"]

        from ..storage.session_manager import SessionManager
        from ..storage.onboarding import mark_milestone, increment_counter

        mgr = SessionManager(root)
        mgr.ensure_initialized()
        
        task_str = f"resolve {scope}" + (f" (budget={budget})" if budget else "")
        session_id = mgr.create_session(scope, task_str, resolved.files, resolved.context)
        resolved.context = f"# dotscope-session: {session_id}\n{resolved.context}"
        
        mark_milestone(root, "first_session")
        increment_counter(root, "sessions_completed")
        return state

class FormattingStage(PipelineStage):
    """Translates Python representations into definitive serialization templates."""
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        from ..ux.formatter import format_resolved
        root = state["root"]
        resolved = state["resolved"]
        fmt = state.get("format", "json")
        
        output = format_resolved(resolved, fmt=fmt, root=root)
        
        # Determine format injection map immediately.
        if fmt == "json":
            state["data"] = json.loads(output)
            state["data"]["source_of_truth"] = state.get("freshness")
        else:
            state["raw_output"] = output
        return state

class VisibilityMetadataStage(PipelineStage):
    """Aggregates all attribution mapping and structural routing directives (Phase II)."""
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if "data" not in state:
            return state
            
        data = state["data"]
        root = state["root"]
        module = state.get("module")
        task = state.get("task")

        # Retrieve the architectural gravity of the requested scope
        gravity_score = 0
        manifest_path = os.path.join(root, ".dotscope", "structural_manifest.json") if root else ""
        if os.path.exists(manifest_path):
            try:
                import json
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.loads(f.read())
                nodes = manifest.get("nodes", [])
                scores = manifest.get("gravity_scores", [])
                if len(nodes) == len(scores):
                    hub_dict = dict(zip(nodes, scores))
                    for f in state["resolved"].files:
                        gravity_score += hub_dict.get(f, 0)
            except Exception:
                pass
                
        metadata = state.setdefault("metadata", {})
        metadata["gravity_score"] = gravity_score
        
        # Attribution hints
        from ..ux.visibility import extract_attribution_hints
        contracts = state.get("_cached_history").implicit_contracts if state.get("_cached_history") else None
        data["attribution_hints"] = extract_attribution_hints(
            state["resolved"].context,
            implicit_contracts=contracts,
            graph_hubs=state.get("_cached_graph_hubs", {}),
            scope_directory=module,
        )

        from ..workflows.intent import load_conventions, load_intents
        conventions = load_conventions(root)
        
        # Constraints mapping
        from ..passes.sentinel.constraints import build_constraints
        invariants = {}
        inv_path = os.path.join(root, ".dotscope", "invariants.json")
        if os.path.exists(inv_path):
            with open(inv_path, "r", encoding="utf-8") as _f:
                invariants = json.loads(_f.read())
        
        scopes_data = {}
        from ..passes.sentinel.checker import _load_scopes_with_antipatterns
        scopes_data = _load_scopes_with_antipatterns(root)
        intents = load_intents(root)
        
        constraints = build_constraints(
            module, root, invariants, scopes_data, intents,
            graph_hubs=state.get("_cached_graph_hubs", {}), task=task,
            conventions=conventions,
        )
        if constraints:
            data["constraints"] = [{"category": c.category, "message": c.message, "file": c.file, "confidence": c.confidence} for c in constraints]

        # Routing guidance
        from ..passes.sentinel.constraints import build_routing_guidance
        vc = None
        try:
            from ..workflows.intent import load_voice_config
            vc = load_voice_config(root)
        except Exception as e:
            logger.debug("Failed loading voice config", exc_info=True)
            
        routing = build_routing_guidance(module, conventions=conventions, voice_config=vc, repo_root=root)
        if routing:
            data["routing"] = [{"category": r.category, "message": r.message, "confidence": r.confidence} for r in routing]

        # Adjacent Routing
        from ..passes.sentinel.constraints import build_adjacent_routing
        scopes_index = {}
        try:
            from ..engine.scanner import load_scopes_index
            scopes_index = load_scopes_index(root)
        except Exception:
            logger.debug("Failed mapping scopes index for adjacent checks", exc_info=True)
            
        adjacent = build_adjacent_routing(module, graph_hubs=state.get("_cached_graph_hubs", {}), all_scopes=scopes_index, conventions=conventions)
        if adjacent:
            data["routing_adjacent"] = [{"scope": r.metadata.get("adjacent_scope", ""), "message": r.message} for r in adjacent]

        # Observation checks
        obs_path = os.path.join(root, ".dotscope", "last_observation.json")
        if os.path.exists(obs_path):
            with open(obs_path, "r", encoding="utf-8") as _f:
                last_obs = json.loads(_f.read())
            if last_obs.get("scope") == module or not last_obs.get("scope"):
                data["last_observation"] = last_obs

        # Voice 
        if vc:
            from ..passes.voice import build_voice_response
            data["voice"] = build_voice_response(vc, root, state["resolved"].files, conventions)

        return state

class HealthAnalyticsStage(PipelineStage):
    """Calculates model accuracy drift alongside Nudges processing."""
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if "data" not in state:
            return state

        data = state["data"]
        root = state["root"]
        module = state.get("module")
        dot_dir = os.path.join(root, ".dotscope") if root else None
        
        if dot_dir and os.path.exists(dot_dir):
            from ..storage.session_manager import SessionManager
            from ..ux.visibility import build_accuracy, check_health_nudges
            from ..workflows.refresh import refresh_status_summary
            
            mgr = SessionManager(root)
            sessions = mgr.get_sessions(limit=200)
            scope_session_ids = {s.session_id for s in sessions if state["scope"] in s.scope_expr}
            observations = [o for o in mgr.get_observations(limit=200) if o.session_id in scope_session_ids]

            accuracy = build_accuracy(observations, state["scope"])
            if accuracy:
                data["accuracy"] = accuracy

            nudges = check_health_nudges(observations, state["scope"], repo_root=root)
            refresh_status = refresh_status_summary(root)
            
            if refresh_status.get("running") and refresh_status.get("current_job") == "repo":
                nudges = nudges or []
                nudges.append({
                    "scope": module, "issue": "repo_refresh_running",
                    "message": "A background repo refresh is rebuilding live scopes.",
                    "suggestion": "dotscope refresh status",
                })
            elif any(job.get("kind") == "repo" for job in refresh_status.get("queued_jobs", [])):
                nudges = nudges or []
                nudges.append({
                    "scope": module, "issue": "repo_refresh_queued",
                    "message": "A background repo refresh is queued for live scope updates.",
                    "suggestion": "dotscope refresh status",
                })
            if nudges:
                data["health_warnings"] = nudges

            from ..storage.near_miss import load_recent_near_misses
            nms = load_recent_near_misses(root, module)
            if nms:
                data["near_misses"] = nms

        # Final structural Assertions Check
        assertions = state.get("assertions", [])
        if assertions:
            from ..engine.assertions import check_output_assertions
            err = check_output_assertions(
                state["resolved"].context,
                data.get("constraints", []),
                assertions, module,
            )
            if err:
                state["halt_error"] = json.dumps(err.to_dict(), indent=2)

        return state

class FinalTelemetryStage(PipelineStage):
    """Publishes completion metrics effectively marking execution closure."""
    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        root = state["root"]
        tracker = state.get("tracker")
        data = state.get("data")
        module = state.get("module")
        repo_tokens = state.get("_repo_tokens", 0)

        # Update Session Summary Metrics efficiently if structured mappings existed.
        if data and tracker and module:
            data["_repo_tokens"] = repo_tokens
            tracker.record_resolve(module, data)
            data.pop("_repo_tokens", None)

        try:
            from ..storage.timing import record_timing
            elapsed_ms = (_time.perf_counter() - state["_resolve_start"]) * 1000
            if root:
                record_timing(root, "resolve", elapsed_ms)
        except Exception:
            logger.debug("Telemetry timing log failed", exc_info=True)
            
        return state

def get_standard_resolve_pipeline() -> Pipeline:
    return Pipeline([
        InitCompilationStage(),
        EnrichmentStage(),
        BudgetExecutionStage(),
        TrackerStage(),
        FormattingStage(),
        VisibilityMetadataStage(),
        HealthAnalyticsStage(),
        FinalTelemetryStage()
    ])
