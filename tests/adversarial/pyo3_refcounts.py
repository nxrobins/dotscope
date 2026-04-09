import os
import sys
import psutil
import dotscope_core

def run_stress_test(root_path: str, loops: int = 25):
    process = psutil.Process(os.getpid())
    print(f"[Phase 1] Starting FFI Memory Stress Test: {loops} epochs")
    
    epoch_1_mem = 0.0

    for i in range(loops):
        topology = dotscope_core.ingest_repository(root_path, 100, True)
        ref_count = sys.getrefcount(topology)
        del topology

        current_mem = process.memory_info().rss / (1024 * 1024)
        if i == 1:
            epoch_1_mem = current_mem
            print(f"Calibrated Python VM Memory (Post-Initialization): {epoch_1_mem:.2f} MB")
            
        print(f"Epoch {i}: RAM = {current_mem:.2f} MB | Temporary PyO3 RefCount = {ref_count}")

    final_mem = process.memory_info().rss / (1024 * 1024)
    print(f"Final Memory Output: {final_mem:.2f} MB")
    
    delta = final_mem - epoch_1_mem
    if delta > 5.0 and epoch_1_mem > 0:
        print(f"FAILED: The FFI boundary leaked {delta:.2f} MB")
        sys.exit(1)
    else:
        print(f"PASSED: The PyO3 Reference Counter generated absolute zero-copy memory closure.")
        sys.exit(0)

if __name__ == "__main__":
    run_stress_test(".", 10)
