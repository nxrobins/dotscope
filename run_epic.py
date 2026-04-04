import sys
import os
import json
import time

sys.path.insert(0, r'D:\dotswarm')

from dotswarm.mcp_server import (
    SwarmControlPlane, 
    _NoOpDotScopeClient, 
    _FileOverlapLockChecker, 
    _NoOpNPMIProvider,
    _ClaudeWorkerRunner, 
    _StderrEscalationHandler
)
from dotswarm.validator import DependencyGraphProvider
from dotswarm.models import SwarmDAG

# Dummy provider that doesn't block validation if not connected fully
class _PermissiveGraph(DependencyGraphProvider):
    def get_cycles(self): return []
    def edges(self): return []
    def nodes(self): return []
    def get_node(self, x): return None

def run():
    print("Initializing dotswarm Layer 2 Control Plane...")
    cp = SwarmControlPlane(
        dotscope_client=_NoOpDotScopeClient(),
        lock_checker=_FileOverlapLockChecker(),
        npmi_provider=_NoOpNPMIProvider(),
        graph_provider=_PermissiveGraph(),
        worker_runner=_ClaudeWorkerRunner(os.getcwd()),
        escalation_handler=_StderrEscalationHandler()
    )

    # Convert the yaml intent into the strict SwarmDAG json format
    dag_json = {
        "epic_id": "dotscope-dogfood",
        "nodes": {
            "phase_1_paths": {
                "id": "phase_1_paths",
                "node_type": "modify",
                "target_files": ["dotscope/discovery.py", "dotscope/paths/repo.py"],
                "objective": "Extract `find_repo_root` from `dotscope/discovery.py` entirely into a new lightweight utility module: `dotscope/paths/repo.py` and update all dotscope codebase imports."
            },
            "phase_2_models": {
                "id": "phase_2_models",
                "node_type": "modify",
                "depends_on": ["phase_1_paths"],
                "target_files": ["dotscope/models.py", "dotscope/models/core.py"],
                "objective": "Move all definitions out of `dotscope/models.py` into their respective specific modules in `dotscope/models/`. Update downstream imports and delete `dotscope/models.py`."
            },
            "phase_3_cli_split": {
                "id": "phase_3_cli_split",
                "node_type": "modify",
                "depends_on": ["phase_1_paths", "phase_2_models"],
                "target_files": ["dotscope/cli.py", "pyproject.toml"],
                "objective": "Deconstruct cli.py via Domain Driven Design into dotscope/cli/ module. Update pyproject.toml scripts."
            },
            "phase_4_mcp_split": {
                "id": "phase_4_mcp_split",
                "node_type": "modify",
                "depends_on": ["phase_3_cli_split"],
                "target_files": ["dotscope/mcp_server.py"],
                "objective": "Modularize mcp_server.py via domain blueprints and tools registrations."
            }
        }
    }
    
    print("\n[✔] Loading SwarmDAG (dotscope-dogfood):")
    for nid in dag_json["nodes"].keys():
        print(f"  └─ {nid}")

    try:
        print("\n[+] Validating graph integrity...")
        dag = SwarmDAG.model_validate(dag_json)
        result = cp.plan_epic("dotscope-dogfood", dag)
        print(json.dumps(result, indent=2))
        
        print("\n[+] Executing Epic Plan (Multi-Agent Dispatch)...")
        exec_result = cp.execute_plan("dotscope-dogfood", dry_run=False)
        print(json.dumps(exec_result, indent=2))
        
        # Loop to show plan_status updates live in the terminal
        while True:
            status = cp.plan_status("dotscope-dogfood")
            
            # Count the amount of completed nodes
            completed = sum(1 for n in status["nodes"].values() if n["status"] == "COMPLETED")
            running = sum(1 for n in status["nodes"].values() if n["status"] == "RUNNING")
            
            print(f"\r  [Dispatch] {completed}/{len(status['nodes'])} completed | {running} running...", end="")
            
            if completed == len(status["nodes"]):
                print("\n\n[✔] Epic Successful!")
                break
            if any(n["status"] in ("ESCALATED", "BLOCKED") for n in status["nodes"].values()):
                print("\n\n[!] Warning: Node Escalated or Blocked")
                break
                
            time.sleep(1)

    except Exception as e:
        print(f"\n[!] Dotswarm Error: {e}")

if __name__ == "__main__":
    run()
