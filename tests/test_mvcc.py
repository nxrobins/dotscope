import os
import struct
import pytest
from dotscope.mcp.mvcc import MvccReaderContext

def test_active_readers_crash_safety(tmp_path):
    """
    The RCU Crash Test: Verify that if an exception is thrown inside the Reader context 
    (simulating an unsafe struct.unpack), the __exit__ decrements the active readers properly.
    """
    root = str(tmp_path)
    dotscope_dir = os.path.join(root, ".dotscope")
    os.makedirs(dotscope_dir, exist_ok=True)
    control_mmap = os.path.join(dotscope_dir, "control.mmap")
    
    # Initialize a 4096-byte control.mmap with 0 readers
    with open(control_mmap, "wb") as f:
        f.write(b'\x00' * 4096)
        
    try:
        with MvccReaderContext(root) as state:
            assert state["status"] == "ready"
            
            # Verify readers incremented to 1
            with open(control_mmap, "r+b") as check_f:
                check_f.seek(8)
                readers = struct.unpack('<i', check_f.read(4))[0]
                assert readers == 1
                
            raise IndexError("Simulated Corruption Crash during unpacking")
    except IndexError:
        pass # Expected crash
        
    # Verify the crash reliably decrements readers back to 0 avoiding NTFS deadlock
    with open(control_mmap, "r+b") as final_f:
        final_f.seek(8)
        readers = struct.unpack('<i', final_f.read(4))[0]
        assert readers == 0, "FATAL: ACTIVE_READERS context manager leaked after crash!"
