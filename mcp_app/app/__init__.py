"""Nordvik steering hub: Python API layer (access, views, audit). ALL DATA IS SIMULATED.

Puts the repository root on sys.path so `mcp_server.server` (the single source of truth for every number)
can be imported from here.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
