"""App-compatibility test harness: install/run a reference Windows app inside the VM
that is running the rebuilt OS (or the reference OS for baseline capture), record
results, and aggregate compat/regression reports.
"""
from __future__ import annotations

import time
from pathlib import Path

from . import qemu
from .util import jdump, jload


def test_app_in_vm(vm: str, app_path: str | None, args: list[str] | None = None,
                   workspace: str | None = None, install_cmd: list[str] | None = None,
                   run_cmd: list[str] | None = None, timeout: int = 120,
                   label: str | None = None) -> dict:
    """Full cycle: put app into the VM, optionally run an install command, run the app,
    capture exit code/output, take a post-run screenshot, and record a result JSON."""
    meta = qemu.vm_status(vm)
    if not meta.get("running"):
        raise qemu.VmError(f"VM '{vm}' is not running")
    shots_dir = Path(meta["dir"]) / "shots"
    result: dict = {
        "kind": "app-test",
        "vm": vm,
        "label": label or (Path(app_path).name if app_path else (run_cmd or ["?"])[0]),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "workspace": workspace,
        "steps": [],
        "pass": False,
    }

    def step(name: str, ok: bool, detail: str = "") -> None:
        result["steps"].append({"step": name, "ok": ok, "detail": detail[:1500]})

    try:
        if app_path:
            local = Path(app_path).expanduser().resolve()
            if not local.exists():
                raise FileNotFoundError(f"app not found: {local}")
            guest = "C:\\uos-tests\\" + local.name
            qemu.vm_exec(vm, "cmd.exe", ["/c", "mkdir C:\\uos-tests 2>nul"], timeout=30)
            put = qemu.vm_put_file(vm, str(local), guest)
            result["app_guest_path"] = put["guest_path"]
            step("put_file", True, f"{put['bytes']} bytes -> {put['guest_path']}")
        else:
            guest = None

        if install_cmd:
            ir = qemu.vm_exec(vm, install_cmd[0], install_cmd[1:], timeout=timeout)
            result["install"] = ir
            step("install", (ir.get("exitcode") or 0) == 0,
                 f"rc={ir.get('exitcode')} out={ir.get('stdout', '')[:300]}")

        cmd = run_cmd or ([guest] if guest else None)
        if not cmd:
            raise ValueError("nothing to run: provide app_path or run_cmd")
        rr = qemu.vm_exec(vm, cmd[0], cmd[1:], timeout=timeout)
        result["run"] = rr
        ok = (rr.get("exitcode") or 0) == 0
        step("run", ok, f"rc={rr.get('exitcode')} out={rr.get('stdout', '')[:300]} "
                        f"err={rr.get('stderr', '')[:200]}")
        result["pass"] = ok
    except qemu.VmError as e:
        step("guest-agent", False, str(e))
    except Exception as e:
        step("error", False, f"{type(e).__name__}: {e}")

    try:
        shot = qemu.vm_screenshot(vm)
        result["post_screenshot"] = shot["png"]
    except Exception as e:
        result["post_screenshot"] = None
        result["screenshot_error"] = str(e)

    result["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")

    if workspace:
        ws = Path(workspace).expanduser().resolve()
        results_dir = ws / "tests" / "results"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = jdump(result, results_dir / f"{stamp}-{result['label']}.json".replace(" ", "_"))
        result["result_file"] = str(out)
        status = "PASS" if result["pass"] else "FAIL"
        from .util import append_md
        append_md(ws / "tests" / "RESULTS.md",
                  f"| {result['finished']} | {result['label']} | {vm} | {status} | "
                  f"{(result['run'] or {}).get('exitcode', '—')} | "
                  f"{Path(result['result_file']).name if result.get('result_file') else '—'} |\n")
    return result


def compat_report(workspace: str) -> dict:
    """Aggregate every recorded app-test into a dated compatibility report."""
    ws = Path(workspace).expanduser().resolve()
    if not (ws / "workspace.json").exists():
        raise FileNotFoundError(f"not a workspace: {ws}")
    results_dir = ws / "tests" / "results"
    results = []
    for f in sorted(results_dir.glob("*.json")):
        try:
            results.append(jload(f))
        except Exception:
            continue
    passed = [r for r in results if r.get("pass")]
    failed = [r for r in results if not r.get("pass")]
    report = {
        "kind": "compat-report",
        "workspace": str(ws),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(results),
        "pass": len(passed),
        "fail": len(failed),
        "pass_rate_pct": round(len(passed) / len(results) * 100, 1) if results else None,
        "labels_passed": sorted({r.get("label", "?") for r in passed}),
        "labels_failed": sorted({r.get("label", "?") for r in failed}),
    }
    out = jdump(report, ws / "reports" / f"compat-{time.strftime('%Y%m%d-%H%M%S')}.json")
    md = out.with_suffix(".md")
    lines = [
        f"# Compatibility report — {report['generated']}",
        "",
        f"{report['pass']}/{report['total']} apps passed "
        f"({report['pass_rate_pct'] if report['pass_rate_pct'] is not None else '—'}%).",
        "",
        "## Passing",
    ]
    lines += [f"- {l}" for l in report["labels_passed"]] or ["- (none yet)"]
    lines += ["", "## Failing", ""]
    lines += [f"- {l}" for l in report["labels_failed"]] or ["- (none)"]
    lines += [
        "",
        "## Next steps for failures",
        "",
        "For each failing app: re-run `test_app_in_vm` capturing output, then either",
        "fix the owning component or add a quirk with `gen_compat_layer`.",
    ]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report["json"] = str(out)
    report["markdown"] = str(md)
    return report


def regression_log(workspace: str, status: str, note: str) -> dict:
    """Append a dated entry to tests/REGRESSIONS.md ('status' e.g. pass|regressed|fixed)."""
    ws = Path(workspace).expanduser().resolve()
    if not (ws / "workspace.json").exists():
        raise FileNotFoundError(f"not a workspace: {ws}")
    from .util import append_md
    path = ws / "tests" / "REGRESSIONS.md"
    if not path.exists():
        path.write_text("# Regression log\n\n| Date | Status | Note |\n|---|---|---|\n",
                        encoding="utf-8")
    append_md(path, f"| {time.strftime('%Y-%m-%d %H:%M')} | {status} | {note.strip()} |\n")
    return {"log": str(path), "status": status, "note": note.strip()[:200]}
