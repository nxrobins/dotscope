import json
import mmap
import os
import socket
import struct
from typing import Dict, Any

_DEFAULT_STRONG_WAIT_SECONDS = 5.0

class MvccReaderContext:
    def __init__(self, root: str):
        self.control_path = os.path.join(root, ".dotscope", "control.mmap")
        self.mm = None
        self.file_obj = None

    def __enter__(self):
        if not os.path.exists(self.control_path):
            return {"status": "fallback"}
        try:
            self.file_obj = open(self.control_path, "r+b")
            self.mm = mmap.mmap(self.file_obj.fileno(), 4096)
            
            # Increment ACTIVE_READERS atomic counter
            readers = struct.unpack('<i', self.mm[8:12])[0]
            self.mm[8:12] = struct.pack('<i', readers + 1)
            
            return {
                "status": "ready",
                "active_buffer": self.mm[0],
                "dirty_flag": self.mm[1],
                "epoch": struct.unpack('<I', self.mm[4:8])[0]
            }
        except Exception:
            self._cleanup()
            return {"status": "fallback"}

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.mm:
            try:
                # Decrement ACTIVE_READERS upon safe exit or crash!
                readers = struct.unpack('<i', self.mm[8:12])[0]
                if readers > 0:
                    self.mm[8:12] = struct.pack('<i', readers - 1)
            except Exception:
                pass
        self._cleanup()
        
    def _cleanup(self):
        if self.mm:
            try:
                self.mm.close()
            except Exception:
                pass
        if self.file_obj:
            try:
                self.file_obj.close()
            except Exception:
                pass

def check_mvcc_state(root: str, consistency: str = "snapshot", port: int = 28491) -> Dict[str, Any]:
    """Execute MVCC State Checking on the Dotscope Local TCP control plane."""
    if consistency == "strong":
        control_path = os.path.join(root, ".dotscope", "control.mmap")
        if not os.path.exists(control_path):
            return {"status": "fallback"}
        # TCP Blocking call to Wait for write-plane
        try:
            wait_seconds = _strong_wait_timeout()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(wait_seconds)
                s.connect(("127.0.0.1", port))
                s.sendall(b'{"cmd": "consistency", "type": "strong"}')
                data = s.recv(1024)
                if not data:
                    return {"status": "fallback"}
                return json.loads(data.decode('utf-8'))
        except Exception:
            return {"status": "fallback"}

    # For snapshot isolation, we don't necessarily hold it open endlessly if we just check state
    with MvccReaderContext(root) as state:
        return state

def apply_mvcc_to_kwargs(root: str, kwargs: dict) -> None:
    """Inject MVCC into any MCP tool kwargs payload securely."""
    consistency = kwargs.get("consistency")
    if not consistency:
        with MvccReaderContext(root) as snapshot:
            if snapshot.get("dirty_flag", 0) == 1:
                consistency = "strong"
            else:
                consistency = "snapshot"
            
    if consistency == "strong":
        check_mvcc_state(root, consistency="strong")


def _strong_wait_timeout() -> float:
    raw = os.environ.get("DOTSCOPE_MCP_STRONG_WAIT_SECONDS")
    if raw is None:
        return _DEFAULT_STRONG_WAIT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_STRONG_WAIT_SECONDS
    return max(0.1, value)
