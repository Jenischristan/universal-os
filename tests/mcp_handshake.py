#!/usr/bin/env python3
"""Race-free MCP stdio handshake check. Run: `python tests/mcp_handshake.py`.

Why this exists
---------------
The original CI handshake piped three JSON-RPC lines into the server and closed
its stdin immediately. mcp 2.x session teardown then cancels the still-running
`tools/list` handler before its response reaches the pipe, silently losing the
response -> flaky `AssertionError: tools/list failed` (observed on GitHub
Actions and reproduced locally: ~10% failures with 39 tools, 0% when stdin is
kept open). A real MCP client never does this: it sends a request and WAITS for
the matching response before proceeding. That is what this script does, in
lockstep, with a watchdog and full diagnostics on failure.

Exit codes: 0 = handshake OK and enough tools listed; 1 = anything else.
Optional argv[1]: per-response timeout in seconds (default 60).
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

MIN_TOOLS = 30
# Spot-check tools across every category so a silent registration failure
# cannot pass a bare count check.
REQUIRED_TOOLS = {
    "iso_inspect",         # ISO control
    "vm_create",           # VM lifecycle
    "vm_exec",             # guest control
    "fingerprint_windows", # reverse engineering
    "init_workspace",      # reconstruction
    "test_app_in_vm",      # test harness
    "kb_search",           # knowledge base
    "env_check",           # meta
}

INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "ci-handshake", "version": "0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}


def main() -> int:
    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    proc = subprocess.Popen(
        [sys.executable, "-m", "universal_os.mcp_server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
    )
    received: list[str] = []
    state = {"failed": False}

    def fail(msg: str) -> None:
        state["failed"] = True
        print(f"HANDSHAKE FAILED: {msg}", file=sys.stderr)
        if received:
            print(f"--- {len(received)} response line(s) received:", file=sys.stderr)
            for i, line in enumerate(received):
                print(f"  [{i}] {line[:200]}", file=sys.stderr)
        else:
            print("--- no response lines received at all", file=sys.stderr)
        stderr = ""
        try:
            stderr = proc.stderr.read() if proc.stderr else ""
        except Exception:
            pass
        if stderr.strip():
            print("--- server stderr:", file=sys.stderr)
            print(stderr, file=sys.stderr)

    watchdog = threading.Timer(timeout * 2, proc.kill)
    watchdog.start()

    def send(payload: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    def wait_for(want_id) -> dict:
        assert proc.stdout is not None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if line == "":  # EOF: server died or the watchdog killed it
                fail(f"server closed stdout before answering id={want_id} "
                     f"(exit code so far: {proc.poll()})")
                sys.exit(1)
            received.append(line.rstrip("\n"))
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate stray non-JSON output, keep waiting
            if msg.get("id") == want_id and ("result" in msg or "error" in msg):
                return msg
        fail(f"timed out waiting for id={want_id} after {timeout}s")
        sys.exit(1)

    try:
        # Lockstep: request -> wait for the matching response -> next request.
        # Never close stdin while a response is in flight (that is the race
        # that made the old CI pipe handshake flaky).
        init = None
        send(INITIALIZE)
        init = wait_for(1)
        if "result" not in init:
            fail(f"initialize returned an error: {json.dumps(init)[:300]}")
            sys.exit(1)
        server_info = init["result"].get("serverInfo", {})
        if server_info.get("name") != "universal-os":
            fail(f"unexpected serverInfo: {server_info}")
            sys.exit(1)

        send(INITIALIZED)          # notification: by design gets no response
        send(TOOLS_LIST)
        listing = wait_for(2)
        if "result" not in listing:
            fail(f"tools/list returned an error: {json.dumps(listing)[:300]}")
            sys.exit(1)
        tools = listing["result"].get("tools", [])
        names = {t.get("name") for t in tools}
        problems: list[str] = []
        if len(tools) < MIN_TOOLS:
            problems.append(f"only {len(tools)} tools listed (need >= {MIN_TOOLS})")
        missing = sorted(REQUIRED_TOOLS - names)
        if missing:
            problems.append(f"required tools missing from tools/list: {missing}")
        for t in tools:
            if not t.get("name") or not t.get("inputSchema"):
                problems.append(f"tool without name/inputSchema: {json.dumps(t)[:120]}")
                break
        if problems:
            fail("; ".join(problems))
            sys.exit(1)

        print(f"MCP OK - {len(tools)} tools listed, all required present")
        return 0
    finally:
        watchdog.cancel()
        if not state["failed"]:
            try:
                if proc.stdin:
                    proc.stdin.close()  # let the server exit cleanly
            except Exception:
                pass
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
