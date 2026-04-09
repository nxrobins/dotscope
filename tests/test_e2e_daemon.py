import os
import time
import socket
import pytest
import subprocess
from dotscope.mcp.mvcc import check_mvcc_state

@pytest.mark.skipif(os.name != 'nt', reason="Testing native MSVC bounds only")
def test_daemon_e2e_tcp_lock(tmp_path):
    root = str(tmp_path)
    dotscope_dir = os.path.join(root, ".dotscope")
    
    daemon_exe = os.path.abspath(os.path.join(
        os.path.dirname(__file__), 
        "../crates/dotscope-core/target/release/dotscope_daemon.exe"
    ))
    
    if not os.path.exists(daemon_exe):
        pytest.skip("Daemon binary not compiled, skipping E2E bounds test")

    port = 28495 # specific port for testing
    
    # Spawn the daemon
    process = subprocess.Popen(
        [daemon_exe, root, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    try:
        # 1. Wait for daemon to initialize mmap and run the initial ingest
        for _ in range(100):
            control_mmap = os.path.join(dotscope_dir, "control.mmap")
            if os.path.exists(control_mmap):
                state = check_mvcc_state(root, consistency="snapshot", port=port)
                if state.get("dirty_flag", 1) == 0:
                    break
            time.sleep(0.1)
        
        # 2. Assert snapshot state is securely created and clean
        assert os.path.exists(control_mmap), "Daemon failed to initialize mmap plane"
        
        state_first = check_mvcc_state(root, consistency="snapshot", port=port)
        assert state_first["status"] == "ready"
        assert state_first["dirty_flag"] == 0
        
        # 3. Request strong TCP block, it should return instantly because DIRTY_FLAG=0
        strong_state = check_mvcc_state(root, consistency="strong", port=port)
        assert strong_state["status"] == "ready"
        assert strong_state["epoch"] >= 0
        
        # 4. Trigger the Token Bucket debounce by writing a file
        dummy_ts = os.path.join(root, "test.ts")
        with open(dummy_ts, "w") as f:
            f.write("export const Test = 1;")
            
        # The daemon debounces for 200ms. We sleep slightly and then request strong consistency.
        # Strong consistency via TCP will block natively until the daemon finishes processing the update!
        time.sleep(0.3)
        strong_after = check_mvcc_state(root, consistency="strong", port=port)
        assert strong_after["status"] == "ready"
        
        assert strong_after["epoch"] > state_first["epoch"], "Epoch did not advance after background daemon rebuilt the A/B tensor!"

    finally:
        process.terminate()
        process.wait()
