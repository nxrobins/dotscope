import logging
import os
from typing import Optional
from ..paths.repo import find_repo_root

_logger = None

def get_mcp_logger(name: str = "dotscope.mcp") -> logging.Logger:
    """Retrieves or configures a structured, isolated logger for the MCP Control Plane.
    
    Critically bypasses stdout/stderr (StreamHandlers) completely to prevent 
    corrupting the JSON-RPC interface utilized by FastMCP back to the agent client.
    Instead, strictly routes all exceptions implicitly into `.dotscope/mcp_debug.log`.
    """
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger(name)
    
    # FastMCP uses root loggers often. Prevent propagation upwards!
    logger.propagate = False

    # Prevent massive log spam unless directly tracking deeper bugs.
    logger.setLevel(logging.DEBUG)

    # We only inject the FileHandler once.
    if not logger.handlers:
        root = find_repo_root()
        if root:
            # Safely create .dotscope directory if missing. 
            # Note: During normal operations dotscope initialization secures this.
            dot_dir = os.path.join(root, ".dotscope")
            os.makedirs(dot_dir, exist_ok=True)
            log_path = os.path.join(dot_dir, "mcp_debug.log")
            
            # Use append mode, 10MB rotations hypothetically (skipping full RotatingFileHandler to minimise dependencies here)
            try:
                # Basic FileHandler
                handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
                
                # Structured Formatting
                formatter = logging.Formatter(
                    fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
                )
                handler.setFormatter(formatter)
                logger.addHandler(handler)
            except OSError:
                # If we cannot create the log file (permissions), fall back to a NullHandler.
                # NEVER write to terminal.
                logger.addHandler(logging.NullHandler())
        else:
            logger.addHandler(logging.NullHandler())

    _logger = logger
    return _logger
