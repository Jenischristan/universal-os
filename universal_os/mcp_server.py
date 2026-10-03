"""universal-os MCP server (stdio). Run with `uos-mcp` or `uos mcp`.

Every tool docstring is written for the AI agent that calls it: what it does, when
to use it in the rebuild loop, and which rules apply. Full rules: RULES.md in the
repo; the loop: SKILL.md; per-phase walkthrough: WORKFLOW.md.
"""
from __future__ import annotations

import json
from pathlib import Path

# Support both MCP SDK generations: 1.x (FastMCP) and 2.x (MCPServer, same decorator API).
try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
except ImportError:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as _Server  # type: ignore[no-redef]

from . import knowledge as kb
from . import qemu, retools, testtools, forgetools
from . import __version__
from .util import which

mcp = _Server(
    "universal-os",
    instructions=(
        "universal-os: reverse engineer a Windows ISO in a sandbox VM and rebuild the OS "
        "ReactOS-style, component by component, until its apps run on the rebuild.\n"
        "Follow the loop in SKILL.md: intake -> fingerprint -> lab -> survey -> route -> "
        "spec -> build -> verify -> field note.\n"
        "Guardrails (moderate): inspect anything inside the VM; NEVER ship Microsoft "
        "binaries/registry hives/fonts, decompiled code, or media links in the rebuilt "
        "OS repo. Interface facts (names/ordinals/versions/structures) are fine. "
        "VM networking is OFF by default; ask the user before enabling it. "
        "Always journal to WORKSPACE.md."
    ),
)


def _ok(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, indent=2, ensure_ascii=False)


# ===========================================================================
# ISO & VM control
# ===========================================================================

@mcp.tool()
def iso_inspect(iso_path: str, max_entries: int = 300) -> str:
    """List an install ISO's contents WITHOUT mounting it (pure ISO9660/Joliet read).

    Use this before any VM work: confirms the image is readable, shows the layout
    (I386/ legacy vs SOURCES/ modern), and surfaces version markers. Run
    fingerprint_windows for the full version verdict."""
    try:
        from . import isofs
        with isofs.IsoImage(iso_path) as iso:
            entries = iso.walk("/", depth=2, limit=max_entries)
            return _ok({
                "iso": str(Path(iso_path).resolve()),
                "volume_id": iso.volume_id,
                "joliet": iso.joliet,
                "entries": entries,
                "note": "untrusted media: never mount on the host; work inside the VM (RULES.md)",
            })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_create(name: str, iso_path: str, disk_gb: int = 30, ram_mb: int = 2048,
              cpus: int = 2, workspace: str = "", network: bool = False,
              force: bool = False) -> str:
    """Create a registered sandbox VM (qcow2 disk + config) for the reference ISO.

    Networking is OFF by default — enabling it needs the user's OK (RULES.md).
    Call vm_boot next. workspace: path of the universal-os workspace this VM belongs to."""
    try:
        return _ok(qemu.vm_create(name, iso_path, disk_gb, ram_mb, cpus,
                                  workspace or None, network, force))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_boot(name: str, wait_seconds: int = 45, boot: str = "d") -> str:
    """Boot the VM headless (boot='d' = CD-ROM first, 'c' = disk). Waits, then reports status.

    Take a screenshot afterwards to see the display. Under pure TCG (no /dev/kvm) a full
    Windows install can take 30-90+ minutes — snapshot right after setup milestones."""
    try:
        return _ok(qemu.vm_boot(name, wait_seconds, boot))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_status(name: str = "") -> str:
    """Report one VM's status, or every registered VM when name is empty."""
    try:
        if name:
            return _ok(qemu.vm_status(name))
        return _ok({"vms": qemu.vm_list()})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_screenshot(name: str) -> str:
    """Capture the VM display to a PNG and return its path.

    Use it after boot, after each setup screen, and after app tests — it is the AI's
    eyes on the guest. Read the PNG with vision to decide the next step."""
    try:
        return _ok(qemu.vm_screenshot(name))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_snapshot(name: str, tag: str) -> str:
    """Save an internal qcow2 snapshot of the running VM (e.g. 'clean-install', 'pre-app-test').

    Snapshot before risky operations: installing apps, changing components, registry edits.
    Restore with vm_restore. Tag naming: kebab-case, one milestone per tag."""
    try:
        return _ok(qemu.vm_snapshot(name, tag))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_restore(name: str, tag: str) -> str:
    """Restore the running VM to a previously saved snapshot (revert experiments safely)."""
    try:
        return _ok(qemu.vm_restore(name, tag))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_exec(name: str, path: str, args: str = "", timeout: int = 120) -> str:
    """Run a command inside the guest via the QEMU guest agent (qemu-ga must be installed).

    args: single string, split on whitespace respecting \\ quoting. Windows guests: use
    'cmd.exe' with args like '/c dir C:\\'. If the agent is missing the error explains
    how to install it (virtio-win ISO for Windows guests)."""
    try:
        import shlex
        argv = shlex.split(args, posix=True) if args else []
        return _ok(qemu.vm_exec(name, path, argv, timeout))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_put_file(name: str, local_path: str, guest_path: str) -> str:
    """Copy a file from the host into the guest (via qemu-ga). Guest paths are Windows-style
    for Windows guests (e.g. C:\\uos-tests\\app.exe). Size cap: ~2GB practical."""
    try:
        return _ok(qemu.vm_put_file(name, local_path, guest_path))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_get_file(name: str, guest_path: str, local_path: str) -> str:
    """Pull a file out of the guest (e.g. an .etl trace, a crash dump, a test log)."""
    try:
        return _ok(qemu.vm_get_file(name, guest_path, local_path))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_mount_iso(name: str, iso_path: str) -> str:
    """Swap the CD-ROM medium in the running VM (e.g. insert virtio-win to install the
    guest agent, then swap back to the reference ISO)."""
    try:
        return _ok(qemu.vm_mount_iso(name, iso_path))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_shutdown(name: str, force: bool = False) -> str:
    """Shut the VM down (ACPI powerdown; falls back to quit after a timeout; force=true
    kills immediately). Registry metadata is kept — vm_boot can start it again."""
    try:
        return _ok(qemu.vm_shutdown(name, force))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def vm_log(name: str, tail: int = 80) -> str:
    """Tail the VM's serial console log and show the qemu command line (debugging boot)."""
    try:
        return _ok(qemu.vm_log(name, tail))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ===========================================================================
# Reverse engineering
# ===========================================================================

@mcp.tool()
def fingerprint_windows(iso_path: str) -> str:
    """Identify the Windows version/build inside an install ISO (any version): layout
    markers, version resources of setup binaries, cversion.ini — with confidence.

    Run this first. It decides the API-surface strategy (NT 5.x vs 6.x differ a lot).
    Version facts are interface facts — fine to journal; media contents stay out of the repo."""
    try:
        return _ok(retools.fingerprint_windows(iso_path))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def analyze_pe(path: str) -> str:
    """Analyze one PE binary (headers, sections, imports, exports, version resource).

    Works on a file extracted INSIDE the VM sandbox or copied out with vm_get_file.
    Reports interface facts only — no disassembly, nothing shippable from the binary."""
    try:
        return _ok(retools.analyze_pe(path))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def dump_api_surface(src_dir: str, out: str, pattern: str = "*.dll",
                     include_exe: bool = False, workspace: str = "") -> str:
    """Dump the interface surface of a directory of reference DLLs: export names,
    ordinals, imports, versions -> JSON + MD. This is the rebuild's target contract.

    IMPORTANT (moderate guardrails): keep the inspected copies OUTSIDE the repo
    (e.g. ~/inspect/); only the generated surface JSON/MD goes into workspace/api/."""
    try:
        return _ok(retools.dump_api_surface(src_dir, out, pattern, include_exe,
                                            workspace or None))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def trace_syscalls(vm: str = "", workspace: str = "", target_app: str = "") -> str:
    """Write a concrete NT-syscall/API tracing plan for this VM (ETW/WPR steps, KDNET
    setup, static-surface fallback) and optionally kick off in-guest prep via qemu-ga.

    Dynamic tracing needs in-guest tooling; this tool gives the exact commands and can
    fetch the results with vm_get_file afterwards."""
    try:
        return _ok(retools.trace_syscalls(vm or None, workspace or None,
                                          target_app or None))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def behavior_diff(baseline: str, current: str, out: str = "", workspace: str = "") -> str:
    """Diff two API-surface dumps (reference vs rebuilt build): per-module export
    coverage, missing/extra exports. THE key progress metric for compatibility."""
    try:
        return _ok(retools.behavior_diff(baseline, current, out or None, workspace or None))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ===========================================================================
# OS reconstruction
# ===========================================================================

@mcp.tool()
def init_workspace(path: str, name: str = "", iso: str = "", version: str = "",
                   target: str = "windows-any") -> str:
    """Create a rebuild workspace: src/{boot,drivers,subsystems,dll,shell,include,apps},
    spec/, api/, tests/, reports/, third-party/, plus WORKSPACE.md journal.

    Everything the AI builds lands here. target examples: windows-xp, windows-7,
    windows-any (version decided after fingerprint_windows)."""
    try:
        return _ok(forgetools.init_workspace(path, name or None, iso or None,
                                             version or None, target))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def scaffold_component(workspace: str, name: str, kind: str = "win32dll",
                       exports: str = "", behavior_note: str = "") -> str:
    """Scaffold a ReactOS-style component: CMakeLists.txt, <name>.spec export table,
    <name>.c with DllMain, README, and an API test file.

    exports: comma-separated export names from the API surface. Implementation always
    comes from behavioral specs written in spec/ — never from decompiled bodies."""
    try:
        exps = [e.strip() for e in exports.split(",") if e.strip()]
        return _ok(forgetools.scaffold_component(workspace, name, kind, exps,
                                                 behavior_note or None))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def gen_api_stub(workspace: str, surface_json: str, module: str,
                 max_stubs: int = 64) -> str:
    """Generate .spec + stub .c for one DLL straight from an API-surface dump
    (stubs return E_NOTIMPL; implement from behavioral specs, highest-import first)."""
    try:
        return _ok(forgetools.gen_api_stub(workspace, surface_json, module, max_stubs))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def gen_compat_layer(workspace: str, module: str, for_apps: str = "",
                     quirks: str = "") -> str:
    """Scaffold a small compat shim for one module: records per-quirk workarounds that
    unblock specific apps (quirks: semicolon-separated; for_apps: comma-separated)."""
    try:
        apps = [a.strip() for a in for_apps.split(",") if a.strip()]
        qs = [q.strip() for q in quirks.split(";") if q.strip()]
        return _ok(forgetools.gen_compat_layer(workspace, module, apps, qs))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def clone_reference_repo(workspace: str, repo: str = "reactos", dest: str = "") -> str:
    """Clone a reference implementation into third-party/ (read-only reference):
    reactos, wine, qemu, virtio-win, or any git URL. Clone repos as needed when a
    component needs proven patterns or test suites."""
    try:
        return _ok(forgetools.clone_reference_repo(workspace, repo, dest or None))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def build_plan(workspace: str, toolchain: str = "rosbe") -> str:
    """Return the concrete build plan for the workspace and check which host toolchains
    are present (cmake/ninja/mingw/RosBE). The AI runs the steps in src/."""
    try:
        return _ok(forgetools.build_plan(workspace, toolchain))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ===========================================================================
# Test harness
# ===========================================================================

@mcp.tool()
def test_app_in_vm(vm: str, app_path: str = "", args: str = "", workspace: str = "",
                   install_cmd: str = "", run_cmd: str = "", timeout: int = 180,
                   label: str = "") -> str:
    """Full app-compat cycle on the rebuilt (or reference) OS: copy the app in, run
    install_cmd then the app, capture exit/output, screenshot, record PASS/FAIL.

    install_cmd/run_cmd: single command lines (argv[0] + args). Results go to
    tests/results/ and tests/RESULTS.md in the workspace. Use reference apps the
    user owns (RULES.md)."""
    try:
        import shlex
        argv = shlex.split(args, posix=True) if args else []
        inst = shlex.split(install_cmd, posix=True) if install_cmd else None
        run = shlex.split(run_cmd, posix=True) if run_cmd else None
        return _ok(testtools.test_app_in_vm(
            vm, app_path or None, argv, workspace or None, inst, run, timeout,
            label or None))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def compat_report(workspace: str) -> str:
    """Aggregate all recorded app tests into a dated compatibility report
    (pass rate, failing labels, next-step guidance)."""
    try:
        return _ok(testtools.compat_report(workspace))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def regression_log(workspace: str, status: str, note: str) -> str:
    """Append a dated entry to tests/REGRESSIONS.md (status: pass|regressed|fixed|wip)."""
    try:
        return _ok(testtools.regression_log(workspace, status, note))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ===========================================================================
# Knowledge base
# ===========================================================================

@mcp.tool()
def kb_search(query: str, limit: int = 10) -> str:
    """Search field notes from previous rebuild attempts (routes, gotchas, versions).
    Search BEFORE starting — prior art saves the whole session."""
    try:
        return _ok({"hits": kb.search(query, limit=limit)})
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def kb_new(os_name: str, component: str, title: str, agent: str = "ai-agent",
           status: str = "working", tags: str = "") -> str:
    """Create a field-note template for this rebuild. Fill it while working, then
    kb_check before sharing. One note per os+component milestone."""
    try:
        return _ok(kb.new_note(os_name, component, title, agent, status, tags))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def kb_check(note: str) -> str:
    """Lint a field note: required sections + prohibited-content scan (no binary dumps,
    no media links). Run before opening a PR."""
    try:
        return _ok(kb.check_note(note))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


@mcp.tool()
def kb_index() -> str:
    """Regenerate knowledge/INDEX.md from all notes' front matter."""
    try:
        return _ok(kb.index())
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ===========================================================================
# Meta
# ===========================================================================

@mcp.tool()
def env_check() -> str:
    """Check the host environment: qemu, qemu-img, git, cmake, ninja, mingw, /dev/kvm.
    Run once at session start; the result decides what the AI can do right now."""
    try:
        kvm = Path("/dev/kvm").exists()
        return _ok({
            "version": __version__,
            "qemu": which("qemu-system-x86_64"),
            "qemu_img": which("qemu-img"),
            "git": which("git"),
            "cmake": which("cmake"),
            "ninja": which("ninja"),
            "mingw_x86_64": which("x86_64-w64-mingw32-gcc"),
            "mingw_i686": which("i686-w64-mingw32-gcc"),
            "kvm": kvm,
            "accel": "kvm" if kvm else "tcg (slow: expect long install times)",
            "install_hint": qemu.qemu_install_hint() if not which("qemu-system-x86_64") else None,
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


PROMPTS = {
    "start-rebuild": (
        "Start a full rebuild session. Reference ISO: {{iso_path}}. Workspace: {{workspace}}. "
        "Follow SKILL.md: kb_search first, fingerprint_windows, env_check, then propose the "
        "phase plan and wait for my OK before creating any VM."
    ),
    "fingerprint": (
        "Fingerprint the Windows ISO at {{iso_path}} with fingerprint_windows and "
        "iso_inspect. Report version, layout, and which API-surface strategy fits. "
        "No VM yet."
    ),
    "boot-and-install": (
        "Create VM '{{vm}}' for {{iso_path}} (no networking), boot it, and walk the "
        "installer by screenshotting after each step. Snapshot 'clean-install' when done."
    ),
    "survey-apis": (
        "In VM '{{vm}}', set up in-guest tracing (trace_syscalls plan), dump the API "
        "surface of the core system DLLs with vm_get_file + dump_api_surface into "
        "{{workspace}}/api/, and journal the top findings in WORKSPACE.md."
    ),
    "scaffold-and-build": (
        "In {{workspace}}, scaffold the top-3 missing modules (behavior_diff or the "
        "surface dump decides) with gen_api_stub, write behavioral specs in spec/, then "
        "build_plan and compile what the host toolchain allows."
    ),
    "test-app": (
        "Test '{{app}}' on the rebuilt build in VM '{{vm}}': test_app_in_vm with "
        "workspace {{workspace}}, then compat_report and regression_log. For every "
        "failure, propose either a component fix or a gen_compat_layer quirk."
    ),
    "field-note": (
        "Wrap up: fill the field note with kb_new/kb_check for os {{os}} component "
        "{{component}}, update WORKSPACE.md phase checkboxes, run kb_index."
    ),
}


@mcp.prompt()
def start_rebuild(iso_path: str, workspace: str = "~/os-forge") -> str:
    """Kick off a full ISO -> rebuilt-OS session following SKILL.md."""
    return PROMPTS["start-rebuild"].replace("{{iso_path}}", iso_path).replace(
        "{{workspace}}", workspace)


@mcp.prompt()
def fingerprint(iso_path: str) -> str:
    """Fingerprint an ISO's Windows version without booting anything."""
    return PROMPTS["fingerprint"].replace("{{iso_path}}", iso_path)


@mcp.prompt()
def boot_and_install(iso_path: str, vm: str = "ref-os") -> str:
    """Boot the reference ISO in a VM and drive the installer via screenshots."""
    return PROMPTS["boot-and-install"].replace("{{iso_path}}", iso_path).replace(
        "{{vm}}", vm)


@mcp.prompt()
def survey_apis(vm: str, workspace: str) -> str:
    """Survey the reference OS's API surface from inside the VM."""
    return PROMPTS["survey-apis"].replace("{{vm}}", vm).replace("{{workspace}}", workspace)


@mcp.prompt()
def scaffold_and_build(workspace: str) -> str:
    """Scaffold the next missing components and build what the host allows."""
    return PROMPTS["scaffold-and-build"].replace("{{workspace}}", workspace)


@mcp.prompt()
def test_app(vm: str, app: str, workspace: str) -> str:
    """Run an app-compat cycle and record the result."""
    return PROMPTS["test-app"].replace("{{vm}}", vm).replace("{{app}}", app).replace(
        "{{workspace}}", workspace)


@mcp.prompt()
def field_note(os: str, component: str) -> str:
    """Write and lint the session's field note."""
    return PROMPTS["field-note"].replace("{{os}}", os).replace("{{component}}", component)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
