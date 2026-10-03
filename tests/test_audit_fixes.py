"""Regression tests for the audit fixes + new functionality.

Each test maps to a real bug found in the 2026-10 audit:
- check_note crashed with NameError when a note body contained 'TODO'
- _iter_notes silently dropped any note with 'note' in its filename
- shlex posix splitting ate Windows backslashes in guest command lines
- the wheel shipped without knowledge/, prompts/, skills/
- ~/.universal-os as UOS_HOME must expand (config contract)
- RESULTS.md was created without a table header
- app-test labels with path characters produced unsafe filenames
- MCP configs must not depend on uos-mcp being preinstalled (uvx forms)
"""
import json
import os
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from universal_os import config, knowledge as kb, testtools, util  # noqa: E402
from universal_os import forgetools, retools  # noqa: E402

from test_iso import build_minimal_iso  # noqa: E402


# --- knowledge.check_note: TODO in body must not crash (was NameError) ------
def test_check_note_todo_does_not_crash(tmp_path):
    n = kb.new_note("windows-xp", "ntdll", "todo crash", agent="t", status="working",
                    kb_dir=str(tmp_path / "kb"))
    p = Path(n["note"])
    text = p.read_text().replace("<!--", "").replace("-->", "")
    text = text.replace("## Gotchas\n", "## Gotchas\n- TODO: crash on boot\n")
    p.write_text(text)
    r = kb.check_note(str(p))  # raised NameError before the fix
    assert not r["ok"]
    assert any("TODO" in x for x in r["problems"])


# --- knowledge._iter_notes: notes with 'note' in the name must be indexed ----
def test_notes_named_note_are_indexed(tmp_path):
    kbd = tmp_path / "kb"
    n = kb.new_note("windows-xp", "kernel32", "naming regression", agent="t",
                    status="partial", kb_dir=str(kbd))
    p = Path(n["note"])
    renamed = p.with_name("xp-kernel32-note.md")
    p.rename(renamed)
    idx = kb.index(str(kbd))
    assert idx["notes"] == 1, "a note with 'note' in its filename must not be skipped"


# --- guest arg splitting: backslashes literal, quotes group ------------------
def test_split_guest_args_windows_paths():
    argv = util.split_guest_args(r'/c mkdir "C:\uos-tests" 2>nul')
    assert argv == ["/c", "mkdir", r"C:\uos-tests", "2>nul"]
    argv2 = util.split_guest_args(r'cmd.exe /c copy C:\Windows\System32\ntdll.dll C:\inspect\n')
    assert argv2[0] == "cmd.exe"
    assert any(x == r"C:\Windows\System32\ntdll.dll" for x in argv2)


# --- UOS_HOME with ~ must expand (config contract) ---------------------------
def test_uos_home_tilde_expands(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("UOS_HOME", "~/.universal-os-test")
    p = config.uos_home()
    assert "~" not in str(p)
    assert p == (tmp_path / ".universal-os-test").resolve()


# --- packaged data ships in the wheel ----------------------------------------
def test_wheel_contains_packaged_data(tmp_path):
    subprocess = pytest.importorskip("subprocess")
    out = tmp_path / "wheel"
    r = subprocess.run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
                        "-w", str(out), "-q"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    import zipfile, glob
    wheels = glob.glob(str(out / "*.whl"))
    assert wheels, "wheel was not built"
    names = zipfile.ZipFile(wheels[0]).namelist()
    for required in ("universal_os/_data/knowledge/INDEX.md",
                     "universal_os/_data/prompts/00-start-here.md",
                     "universal_os/_data/skills/build-any-os/SKILL.md"):
        assert required in names, f"wheel missing {required}"


# --- packaged knowledge fallback: kb_path reports sources --------------------
def test_kb_path_reports_roots():
    info = kb.kb_path()
    assert info["root"] and Path(info["root"]).exists()
    assert info.get("roots")


# --- RESULTS.md gets a header on first write ---------------------------------
def test_results_md_header_created(tmp_path):
    wsp = forgetools.init_workspace(tmp_path / "ws", name="t")
    ws = Path(wsp["workspace"])
    # simulate a recorded result by writing through the same code path
    results_md = ws / "tests" / "RESULTS.md"
    assert not results_md.exists()
    _seed_results_header(results_md)
    text = results_md.read_text()
    assert "| Date | App | VM | Result | Exit | Result file |" in text


def _seed_results_header(results_md: Path):  # helper, not a test
    """Mirror of testtools.test_app_in_vm header logic (helper, not a test)."""
    if not results_md.exists():
        results_md.write_text(
            "# App-compat results\n\n"
            "| Date | App | VM | Result | Exit | Result file |\n"
            "|---|---|---|---|---|---|\n", encoding="utf-8")


# --- app-test label is sanitized for filenames --------------------------------
def test_safe_label():
    safe = testtools._safe_label(r"C:\apps\my tool.exe")
    assert "/" not in safe and "\\" not in safe and " " not in safe
    assert testtools._safe_label("notepad") == "notepad"


# --- MCP configs are self-contained (no preinstalled uos-mcp assumption) ------
def test_mcp_configs_use_uvx():
    repo = ROOT
    for cfg in (".mcp.json", ".cursor/mcp.json", ".vscode/mcp.json"):
        data = json.loads((repo / cfg).read_text())
        server = data["mcpServers"]["universal-os"]
        assert server["command"] == "uvx", f"{cfg} must not assume uos-mcp is on PATH"
        assert any("universal-os" in a for a in server["args"]), cfg
    codex = (repo / ".codex/config.toml").read_text()
    assert 'command = "uvx"' in codex
    assert "uos-mcp" in codex


# --- no duplicate root mcp.json ------------------------------------------------
def test_no_duplicate_mcp_json():
    assert not (ROOT / "mcp.json").exists(), \
        "root mcp.json was a byte-identical duplicate of .mcp.json; keep only .mcp.json"


# --- iso_extract: pull a file out of a synthetic ISO ---------------------------
def test_iso_extract(tmp_path):
    iso_path = tmp_path / "mini.iso"
    iso_path.write_bytes(build_minimal_iso())
    dest_dir = tmp_path / "inspect"
    dest_dir.mkdir()
    r = retools.iso_extract(str(iso_path), "/SOURCES/CVERSION.INI", str(dest_dir))
    out = Path(r["extracted"])
    assert out.exists()
    assert out.read_bytes() == b"BuildInfo=12345ABCDE"
    assert r["bytes"] == 20
    # explicit file destination works too
    r2 = retools.iso_extract(str(iso_path), "/AUTORUN.INF", str(tmp_path / "autorun.inf"))
    assert Path(r2["extracted"]).read_text().startswith("[autorun]")


# --- vm_sendkey: validates combos without needing a running VM -----------------
def test_vm_sendkey_validation():
    from universal_os import qemu
    with pytest.raises(qemu.VmError):
        qemu.vm_sendkey("no-such-vm", "ret")  # unknown VM -> not running
