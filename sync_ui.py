import os
import sys
import shutil
from pathlib import Path

def sync_ui(source_dir: str):
    """
    Synchronizes the compiled standalone dotscope-ui dist 
    into the dotscope python assets payload bridging the headless gap.
    """
    python_repo_root = Path(__file__).resolve().parent
    assets_dir = python_repo_root / "dotscope" / "assets" / "ui"
    
    src = Path(source_dir)
    
    print(f"Syncing standalone UI artifacts from {src} -> {assets_dir}")
    
    if not src.exists():
        print(f"Error: Target UI source {src} does not exist.")
        sys.exit(1)
        
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
        
    shutil.copytree(src, assets_dir)
    
    # Verify index.html exists conceptually
    if not (assets_dir / "index.html").exists():
        print(f"Warning: Extracted repo does not seem to contain index.html.")
        
    print("UI Sync complete.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default local development assumption logic relative to dotscope root
        default_ui = Path(__file__).resolve().parent.parent / "dotscope-ui" / "dotscope" / "assets" / "ui"
        if default_ui.exists():
            sync_ui(str(default_ui))
        else:
            print("Usage: python sync_ui.py <path_to_dotscope_ui_dist>")
            sys.exit(1)
    else:
        sync_ui(sys.argv[1])
