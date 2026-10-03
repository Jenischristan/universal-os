"""Smoke tests: workspace lifecycle, scaffolds, api stubs, behavior diff, kb, ppm/png."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from universal_os import forgetools, retools, testtools, knowledge as kb  # noqa: E402
from universal_os.ppm import ppm_to_png_bytes  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pe import build_minimal_pe  # noqa: E402


@pytest.fixture()
def wsp(tmp_path):
    ws = forgetools.init_workspace(tmp_path / "os-forge", name="forge-test",
                                   iso="C:/isos/xp.iso", version="5.1.2600")
    return Path(ws["workspace"])


@pytest.fixture()
def surfaces(tmp_path):
    ref, cur = tmp_path / "ref", tmp_path / "cur"
    ref.mkdir(); cur.mkdir()
    (ref / "test.dll").write_bytes(build_minimal_pe(("NtCreateFile", "NtClose", "NtWait")))
    (cur / "test.dll").write_bytes(build_minimal_pe(("NtCreateFile", "NtClose", "NtExtra")))
    s1 = retools.dump_api_surface(str(ref), str(tmp_path / "surface-ref.json"))
    s2 = retools.dump_api_surface(str(cur), str(tmp_path / "surface-cur.json"))
    return s1, s2


def test_workspace_flow(wsp):
    assert (wsp / "workspace.json").exists()
    assert (wsp / "src/dll").exists() and (wsp / "WORKSPACE.md").exists()


def test_scaffold(wsp):
    sc = forgetools.scaffold_component(str(wsp), "kernel32_lite",
                                       exports=["CreateFileW", "CloseHandle"])
    assert Path(sc["files"][1]).read_text().count("@ stdcall") == 2
    assert "E_NOTIMPL" not in Path(sc["files"][2]).read_text()  # scaffold, not stubs


def test_surface_and_diff(tmp_path, surfaces, wsp):
    s1, s2 = surfaces
    assert s1["modules"] == 1 and s1["total_exports"] == 3
    d = retools.behavior_diff(str(tmp_path / "surface-ref.json"),
                              str(tmp_path / "surface-cur.json"), workspace=str(wsp))
    assert abs(d["summary"]["overall_coverage_pct"] - 66.67) < 0.1, d["summary"]
    assert d["summary"]["total_missing_in_rebuild"] == 1  # NtWait missing
    assert (wsp / "reports").glob("behavior-diff-*.json")


def test_api_stub(wsp, surfaces):
    s1, _ = surfaces
    g = forgetools.gen_api_stub(str(wsp), s1["json"], "test.dll", out_name="test_lite")
    c = Path(g["c"]).read_text()
    assert "NtCreateFile" in c and "E_NOTIMPL" in c
    assert Path(g["spec"]).read_text().count("@ stdcall") == 3


def test_kb(tmp_path):
    kbd = tmp_path / "kb"
    n = kb.new_note("windows-xp", "ntdll", "first syscall sweep", agent="test",
                    status="working", kb_dir=str(kbd))
    p = Path(n["note"])
    assert p.exists()
    chk = kb.check_note(str(p))
    assert not chk["ok"] and any("unfilled" in x for x in chk["problems"])
    text = p.read_text()
    text = re.sub(r"<!--.*?-->", "filled.", text, flags=re.S).replace("TODO", "done")
    p.write_text(text)
    assert kb.check_note(str(p))["ok"]
    hits = kb.search("syscall sweep", kb_dir=str(kbd))
    assert len(hits) == 1
    idx = kb.index(str(kbd))
    assert idx["notes"] == 1 and (Path(idx["index"])).exists()


def test_ppm_png():
    w, h = 4, 3
    ppm = b"P6\n%d %d\n255\n" % (w, h) + bytes(range(w * h * 3))
    png = ppm_to_png_bytes(ppm)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IHDR" in png and b"IEND" in png


def test_regress_and_report(wsp):
    r = testtools.regression_log(str(wsp), "regressed", "notepad.exe: no text render")
    assert "REGRESSIONS.md" in r["log"]
    rep = testtools.compat_report(str(wsp))
    assert rep["total"] == 0  # no results yet, but report generates


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        wsp = forgetools.init_workspace(tmp / "os-forge", name="t")
        test_workspace_flow(Path(wsp["workspace"]))
    test_ppm_png()
    print("smoke tests OK (direct run; use pytest for the full suite)")
