"""Paths and persistent state for universal-os.

Layout under UOS_HOME (default ~/.universal-os):
    vms/<name>/          disk.qcow2, qmp.sock, ga.sock, serial.log, shots/, logs/
    state/vms.json       VM registry: name -> metadata (pid, disk, iso, snapshots, ...)
Workspaces (the rebuilt-OS source trees) live wherever the user points them; the registry
only records their paths.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def uos_home() -> Path:
    home = os.environ.get("UOS_HOME", "")
    if home.strip():
        p = Path(home).expanduser().resolve()
    else:
        p = Path("~/.universal-os").expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def vms_dir() -> Path:
    d = uos_home() / "vms"
    d.mkdir(parents=True, exist_ok=True)
    return d


def vm_dir(name: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    d = vms_dir() / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_file() -> Path:
    d = uos_home() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d / "vms.json"


def _read_state() -> dict:
    f = state_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"vms": {}}


def _write_state(state: dict) -> None:
    state_file().write_text(json.dumps(state, indent=2), encoding="utf-8")


def vm_get(name: str) -> dict | None:
    return _read_state()["vms"].get(name)


def vm_set(name: str, meta: dict) -> dict:
    state = _read_state()
    state["vms"][name] = meta
    _write_state(state)
    return meta


def vm_del(name: str) -> None:
    state = _read_state()
    state["vms"].pop(name, None)
    _write_state(state)


def vm_all() -> dict:
    return _read_state()["vms"]


def default_workspace_hint() -> str:
    return str(Path("~/os-forge").expanduser())


def find_workspace(path: str | None) -> Path:
    """Resolve a workspace directory, preferring $PWD if it looks like a workspace."""
    if path:
        p = Path(path).expanduser().resolve()
        if (p / "workspace.json").exists():
            return p
        raise FileNotFoundError(f"not a universal-os workspace (no workspace.json): {p}")
    cwd = Path.cwd()
    if (cwd / "workspace.json").exists():
        return cwd
    raise FileNotFoundError(
        "no workspace.json here; run 'uos forge init <dir>' first or pass the workspace path"
    )


def eprint(*a) -> None:
    print(*a, file=sys.stderr)
