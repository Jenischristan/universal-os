"""The CI MCP handshake contract, enforced from the pytest suite too.

Runs tests/mcp_handshake.py (a lockstep stdio client) in a subprocess so that
a broken server fails locally exactly the way CI would, with the same
diagnostics. The script itself documents the stdin-close teardown race that
motivated it.
"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "mcp_handshake.py"


def test_mcp_stdio_handshake_lists_required_tools():
    r = subprocess.run([sys.executable, str(SCRIPT), "60"],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, (
        f"handshake failed (exit {r.returncode})\nstdout:\n{r.stdout}\n"
        f"stderr:\n{r.stderr}")
    assert "MCP OK" in r.stdout
