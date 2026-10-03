"""Tests for the workspace/VM tools added in v0.2.1 and their contracts.

- vm_network_config: real registry update (applies next boot), NAT only
  (bridge raises instead of pretending), unknown VM raises.
- workspace_status: ready/incomplete/missing states from the real structure.
- cleanup_workspace: dry run by default; confirm deletes ONLY regenerable
  junk; third-party/, sources, journal and reports are never touched.
- iso_verify (MCP tool): real ISO structural check against the fixture image.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from universal_os import config, forgetools, qemu  # noqa: E402

from test_iso import build_minimal_iso  # noqa: E402


# --- vm_network_config -------------------------------------------------------
@pytest.fixture()
def vm_registry(tmp_path, monkeypatch):
    """Isolated UOS_HOME with a fake registered VM (no qemu binary needed)."""
    monkeypatch.setenv("UOS_HOME", str(tmp_path / "uos-home"))
    config.vm_set("t-vm", {
        "name": "t-vm", "dir": str(tmp_path / "t-vm"), "disk": "disk.qcow2",
        "iso": "ref.iso", "ram_mb": 2048, "cpus": 2, "network": False,
        "workspace": None, "snapshots": [], "pid": None, "created": "2026-10-03",
    })
    return tmp_path


def test_vm_network_config_updates_registry(vm_registry):
    r = qemu.vm_network_config("t-vm", True)
    assert r["network_enabled"] is True and r["mode"] == "nat"
    assert config.vm_get("t-vm")["network"] is True
    r2 = qemu.vm_network_config("t-vm", False)
    assert r2["network_enabled"] is False
    assert config.vm_get("t-vm")["network"] is False


def test_vm_network_config_bridge_raises_instead_of_pretending(vm_registry):
    from universal_os.qemu import VmError
    with pytest.raises(VmError, match="bridge"):
        qemu.vm_network_config("t-vm", True, nat=False)
    # the failed attempt must not have flipped the flag
    assert config.vm_get("t-vm")["network"] is False


def test_vm_network_config_unknown_vm_raises(vm_registry):
    with pytest.raises(Exception, match="unknown VM"):
        qemu.vm_network_config("no-such-vm", True)


# --- workspace_status --------------------------------------------------------
def test_workspace_status_ready(tmp_path):
    ws = forgetools.init_workspace(tmp_path / "ws", name="t")
    st = forgetools.workspace_status(str(tmp_path / "ws"))
    assert st["status"] == "ready"
    assert st["dirs_missing"] == []
    assert st["journal"]["present"] is True
    assert st["journal"]["last_line"]  # journal has content
    assert ws["workspace"]  # init returned something usable


def test_workspace_status_incomplete(tmp_path):
    ws = tmp_path / "partial"
    ws.mkdir()
    (ws / "src").mkdir()
    st = forgetools.workspace_status(str(ws))
    assert st["status"] == "incomplete"
    assert "third-party" in st["dirs_missing"]
    assert st["journal"]["present"] is False


def test_workspace_status_missing(tmp_path):
    st = forgetools.workspace_status(str(tmp_path / "nope"))
    assert st["status"] == "missing"
    assert "init_workspace" in st["hint"]


# --- cleanup_workspace -------------------------------------------------------
def _make_workspace_with_junk(tmp_path):
    ws = forgetools.init_workspace(tmp_path / "ws", name="t")["workspace"]
    w = Path(ws)
    (w / "src" / "__pycache__").mkdir(parents=True)
    (w / "src" / "__pycache__" / "mod.c.pyc").write_text("junk")
    (w / "src" / "kernel32" / "build").mkdir(parents=True)
    (w / "src" / "kernel32" / "build" / "k.obj").write_text("junk")
    (w / "tests" / ".pytest_cache").mkdir()
    (w / "spec" / "draft.tmp").write_text("junk")
    # things that MUST survive
    (w / "src" / "kernel32" / "kernel32.c").write_text("/* source */")
    (w / "third-party" / "reactos" / "build").mkdir(parents=True)
    (w / "third-party" / "reactos" / "build" / "kept.bin").write_text("keep me")
    (w / "reports" / "report.md").write_text("keep me")
    return w


def test_cleanup_dry_run_lists_but_deletes_nothing(tmp_path):
    w = _make_workspace_with_junk(tmp_path)
    r = forgetools.cleanup_workspace(str(w))
    assert r["deleted"] is False and r["count"] >= 4
    assert any("__pycache__" in x for x in r["would_remove"])
    assert any("build" in x for x in r["would_remove"])
    # nothing was deleted
    assert (w / "src" / "__pycache__" / "mod.c.pyc").exists()
    assert (w / "src" / "kernel32" / "build" / "k.obj").exists()


def test_cleanup_confirm_deletes_only_junk(tmp_path):
    w = _make_workspace_with_junk(tmp_path)
    r = forgetools.cleanup_workspace(str(w), confirm=True)
    assert r["deleted"] is True and r["count"] >= 4
    # junk gone
    assert not (w / "src" / "__pycache__").exists()
    assert not (w / "src" / "kernel32" / "build").exists()
    assert not (w / "tests" / ".pytest_cache").exists()
    assert not (w / "spec" / "draft.tmp").exists()
    # everything promised safe survives
    assert (w / "src" / "kernel32" / "kernel32.c").exists()
    assert (w / "third-party" / "reactos" / "build" / "kept.bin").exists()
    assert (w / "reports" / "report.md").exists()
    assert (w / "WORKSPACE.md").exists()


def test_cleanup_missing_workspace_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        forgetools.cleanup_workspace(str(tmp_path / "nope"))


# --- iso_verify (imported from the MCP server module) ------------------------
def test_iso_verify_reports_structure(tmp_path):
    from universal_os.mcp_server import iso_verify
    iso = tmp_path / "test.iso"
    iso.write_bytes(build_minimal_iso())
    out = iso_verify(str(iso))
    assert '"status": "verified"' in out
    assert '"has_sources": true' in out.replace("True", "true")


def test_iso_verify_bad_path_reports_error(tmp_path):
    from universal_os.mcp_server import iso_verify
    out = iso_verify(str(tmp_path / "missing.iso"))
    assert '"error"' in out
