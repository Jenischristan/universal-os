"""OS reconstruction tools: workspaces, ReactOS-style component scaffolds, API stubs,
compat layers, reference-repo cloning, build plans.

Generated code is always clean-room: ReactOS-style C with .spec export files, written
from *behavioral specs and interface facts* — never from decompiled bodies (RULES.md).
"""
from __future__ import annotations

import time
from pathlib import Path

from .util import jdump, jload, run, which

REFERENCE_REPOS = {
    "reactos": "https://github.com/reactos/reactos.git",
    "wine": "https://gitlab.winehq.org/wine/wine.git",
    "wine-gecko": "https://github.com/wine-mirror/wine-gecko.git",
    "reactos-bootcd-tests": "https://github.com/reactos/reactos.git",
    "winehq-apitestsuite": "https://github.com/wine-mirror/wine.git",
    "qemu": "https://gitlab.com/qemu-project/qemu.git",
    "virtio-win": "https://github.com/virtio-win/kvm-guest-drivers-windows.git",
    "msys2-runtime": "https://github.com/msys2/msys2-runtime.git",
}

CMAKE_TEMPLATE = """\
# {name} — universal-os component ({kind})
# ReactOS-style: exports declared in {name}.spec, built with the ROSBE/MinGW toolchain.

add_library({name} MODULE
    {name}.c
    {name}.spec
)

set_entrypoint({name} DllMain 0)
set_module_type({name} win32dll)

target_link_libraries({name} ${{PSEH_LIB}})

add_cd_file(TARGET {name} DESTINATION reactos/system32 FOR all)
"""

SPEC_TEMPLATE = """\
# {name}.spec — export list for the {name} DLL.
# {export_note}
# Ordinals/names come from the reference API surface (interface facts only).
"""

C_TEMPLATE = """\
/*
 * PROJECT:     {name}
 * LICENSE:     GPL-2.0-or-later (ReactOS-style clean-room reimplementation)
 * PURPOSE:     {purpose}
 * COPYRIGHT:   {year} universal-os generated scaffold (see RULES.md)
 */

/* INCLUDES *****************************************************************/

#include <windef.h>
#include <winbase.h>

/* GLOBALS ******************************************************************/

/* FUNCTIONS ****************************************************************/

static BOOL
WINAPI
{under}DllMain(HINSTANCE hInstance, DWORD dwReason, LPVOID lpReserved)
{{
    UNREFERENCED_PARAMETER(hInstance);
    UNREFERENCED_PARAMETER(lpReserved);

    switch (dwReason)
    {{
        case DLL_PROCESS_ATTACH:
            DisableThreadLibraryCalls(hInstance);
            /* TODO: one-time init — keep it tiny; real behavior comes from specs */
            break;
        case DLL_PROCESS_DETACH:
            break;
    }}
    return TRUE;
}}
"""

STUB_FUNC_TEMPLATE = """\
/*
 * @implemented_stub
 * Reference behavior (from spec {spec_note}):
 *   {behavior}
 */
{ret} WINAPI
{export}({params})
{{
    /* TODO: implement from behavioral spec. Stub returns {default_return}. */
    return {default_return};
}}

"""

README_TEMPLATE = """\
# {name}

{kind} component of the rebuilt OS in this workspace.

- Export contract: `{name}.spec` (names/ordinals from the reference API surface)
- Status log: `../WORKSPACE.md`

## Ground rules (short form — full text in RULES.md)
- Implement from **behavioral specs** written by observing the reference OS in the VM.
- **Never** paste decompiled output or reference binary data into these sources.
- Update `../WORKSPACE.md` with what you implemented, what you verified, what is next.
"""

TEST_TEMPLATE = """\
/*
 * {name} API test — ReactOS rosautotest/APITests style.
 * Each test asserts *documented* behavior from the behavioral spec, not observed hex dumps.
 */
#include <windef.h>
#include <winbase.h>
#include <stdio.h>

static INT g_failures = 0;

#define CHECK(expr) do {{ \\
    if (!(expr)) {{ \\
        printf("FAIL %s:%d: %s\\n", __FILE__, __LINE__, #expr); \\
        g_failures++; \\
    }} \\
}} while (0)

int
main(int argc, char **argv)
{{
    UNREFERENCED_PARAMETER(argc);
    UNREFERENCED_PARAMETER(argv);

    /* TODO: call {name} exports with spec-defined inputs; assert spec-defined outputs. */
    printf("{name} tests: %d failure(s)\\n", g_failures);
    return g_failures ? 1 : 0;
}}
"""

SHIM_TEMPLATE = """\
/*
 * {name} compatibility shim — forwards to the rebuilt OS implementation, adjusting
 * behavior quirks that apps rely on. Document every quirk with the app it unblocks.
 */
#include <windef.h>
#include <winbase.h>

/* Known app-compat quirks handled here:
{quirks}
 */

BOOL WINAPI
DllMain(HINSTANCE hInstance, DWORD dwReason, LPVOID lpReserved)
{{
    UNREFERENCED_PARAMETER(hInstance);
    UNREFERENCED_PARAMETER(lpReserved);
    switch (dwReason)
    {{
        case DLL_PROCESS_ATTACH:
            DisableThreadLibraryCalls(hInstance);
            break;
        case DLL_PROCESS_DETACH:
            break;
    }}
    return TRUE;
}}
"""

WORKSPACE_MD = """\
# {name} — universal-os workspace journal

Anything not written here is lost at the next context compaction. Keep it current.

| Field | Value |
|---|---|
| Created | {now} |
| Reference ISO | {iso} |
| Reference version | {version} |
| Compatibility target | {target} |
| Guardrail level | moderate (see RULES.md) |

## Phase status

- [ ] fingerprint — `uos re fingerprint <iso>` / `fingerprint_windows`
- [ ] lab — VM created and booted from the reference ISO
- [ ] survey — API surface dumped (interface facts), trace plans written
- [ ] route — subsystem order chosen, reference repos cloned
- [ ] first build — at least one component compiles
- [ ] first boot — rebuilt image boots in a VM
- [ ] first app — a reference Windows app runs on the rebuild
- [ ] field note — knowledge-base entry drafted

## Log

### {now}
Workspace created.
"""

SUBSYSTEM_ORDER = [
    "boot", "kernel (ntoskrnl)", "hal", "rtl (ntdll)", "win32k (kernel-mode win32)",
    "csrss + smss", "core dlls: kernel32, user32, gdi32, advapi32",
    "shell subsystem", "user-mode services", "msvcrt + crt support",
    "higher-level stacks (winsock, ole32, ...)",
]


def init_workspace(path: str, name: str | None = None, iso: str | None = None,
                   version: str | None = None, target: str = "windows-any") -> dict:
    ws = Path(path).expanduser().resolve()
    name = name or ws.name
    if ws.exists() and any(ws.iterdir()) and not (ws / "workspace.json").exists():
        raise FileExistsError(f"{ws} is not empty and is not a universal-os workspace")
    for d in ("vm", "iso", "spec", "api", "src", "tests", "third-party", "reports", "tools"):
        (ws / d).mkdir(parents=True, exist_ok=True)
    for d in ("boot", "drivers", "subsystems", "dll", "shell", "include", "apps"):
        (ws / "src" / d).mkdir(parents=True, exist_ok=True)
    cfg = {
        "kind": "universal-os-workspace",
        "name": name,
        "version": 1,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reference_iso": iso,
        "reference_version": version,
        "target": target,
        "guardrails": "moderate",
        "artifacts": {},
    }
    jdump(cfg, ws / "workspace.json")
    (ws / "WORKSPACE.md").write_text(
        WORKSPACE_MD.format(name=name, now=time.strftime("%Y-%m-%d %H:%M:%S"),
                            iso=iso or "TBD", version=version or "TBD", target=target),
        encoding="utf-8")
    return {"workspace": str(ws), "name": name,
            "layout": ["WORKSPACE.md", "workspace.json", "vm/", "iso/", "spec/", "api/",
                       "src/{boot,drivers,subsystems,dll,shell,include,apps}",
                       "tests/", "third-party/", "reports/", "tools/"]}


def scaffold_component(workspace: str, name: str, kind: str = "win32dll",
                       exports: list[str] | None = None,
                       behavior_note: str | None = None) -> dict:
    """Create a ReactOS-style component: CMakeLists.txt, .spec, .c with DllMain + stubs,
    and an API test file."""
    ws = Path(workspace).expanduser().resolve()
    if not (ws / "workspace.json").exists():
        raise FileNotFoundError(f"not a workspace: {ws}")
    comp_dir = ws / "src" / "dll" / name
    comp_dir.mkdir(parents=True, exist_ok=True)

    export_note = ("fill from the reference API surface (dump_api_surface output)"
                   if not exports else f"{len(exports)} exports from the reference surface")
    (comp_dir / "CMakeLists.txt").write_text(
        CMAKE_TEMPLATE.format(name=name, kind=kind), encoding="utf-8")
    (comp_dir / f"{name}.spec").write_text(
        SPEC_TEMPLATE.format(name=name, export_note=export_note)
        + ("".join(f"@ stdcall {e}()\n" for e in exports) if exports else "")
        + ("\n# stubs above: signature fill-in comes from the behavioral spec\n"
           if exports else ""),
        encoding="utf-8")
    purpose = behavior_note or f"Clean-room implementation of {name}"
    (comp_dir / f"{name}.c").write_text(
        C_TEMPLATE.format(name=name, purpose=purpose, year=time.strftime("%Y"),
                          under=""), encoding="utf-8")
    (comp_dir / "README.md").write_text(
        README_TEMPLATE.format(name=name, kind=kind), encoding="utf-8")
    tests_dir = ws / "tests" / name
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_main.c").write_text(
        TEST_TEMPLATE.format(name=name), encoding="utf-8")

    return {
        "component": name,
        "files": [str(comp_dir / f) for f in
                  ("CMakeLists.txt", f"{name}.spec", f"{name}.c", "README.md")]
                  + [str(tests_dir / "test_main.c")],
        "next": [
            f"fill {name}.spec with the real export list (dump_api_surface output)",
            "write the behavioral spec in spec/ before implementing each export",
            "implement one export at a time; verify with the test file and in-VM tests",
            f"append a progress note to {ws}/WORKSPACE.md",
        ],
    }


_PARAM_FALLBACK = "VOID"


def _guess_params(fn: str) -> str:
    return _PARAM_FALLBACK  # real signatures come from behavioral specs, not guessing


def gen_api_stub(workspace: str, surface_json: str, module: str,
                 max_stubs: int = 64, out_name: str | None = None) -> dict:
    """Generate .spec + stub .c for one module from an API-surface dump."""
    ws = Path(workspace).expanduser().resolve()
    surface = jload(Path(surface_json))
    mod = next((m for m in surface.get("modules", [])
                if m.get("module", "").lower() == module.lower()), None)
    if mod is None:
        raise ValueError(f"module '{module}' not in surface; got: "
                         f"{[m.get('module') for m in surface.get('modules', [])][:20]}")
    exports = (mod.get("exports") or [])[:max_stubs]
    name = out_name or Path(module).stem.lower().replace("-", "_")
    comp = scaffold_component(workspace, name, behavior_note=
                              f"Stub scaffold generated from {surface_json} ({module})")
    spec_path = ws / "src" / "dll" / name / f"{name}.spec"
    spec_path.write_text(
        SPEC_TEMPLATE.format(name=name, export_note=
                             f"{len(exports)} exports from {mod.get('module')} "
                             f"(version {mod.get('version')})")
        + "".join(f"@ stdcall {e}()\n" for e in exports),
        encoding="utf-8")
    c_path = ws / "src" / "dll" / name / f"{name}.c"
    body = C_TEMPLATE.format(name=name, purpose=f"Stubs for {mod.get('module')}",
                             year=time.strftime("%Y"), under="")
    stubs = "".join(
        STUB_FUNC_TEMPLATE.format(ret="HRESULT", export=e, params=_PARAM_FALLBACK,
                                  default_return="E_NOTIMPL",
                                  spec_note=f"{mod.get('module')}:{e}",
                                  behavior="documented in spec/ before implementing")
        for e in exports)
    c_path.write_text(body + stubs, encoding="utf-8")
    return {"component": name, "spec": str(spec_path), "c": str(c_path),
            "stubs_generated": len(exports),
            "truncated": len(mod.get("exports") or []) > max_stubs,
            "warning": "stubs return E_NOTIMPL; implement from behavioral specs, top imports first"}


def gen_compat_layer(workspace: str, module: str, for_apps: list[str] | None = None,
                     quirks: list[str] | None = None) -> dict:
    """Scaffold a compat shim: small DLL that adjusts rebuild behavior to what real apps expect."""
    ws = Path(workspace).expanduser().resolve()
    if not (ws / "workspace.json").exists():
        raise FileNotFoundError(f"not a workspace: {ws}")
    name = f"compat_{module.lower().replace('-', '_').replace('.', '_')}"
    comp_dir = ws / "src" / "dll" / name
    comp_dir.mkdir(parents=True, exist_ok=True)
    q = quirks or []
    apps = for_apps or []
    quirk_lines = "".join(f" * - {s} (unblocks: {', '.join(apps) or 'TBD'})\n"
                          for s in q) or " * - (none recorded yet — add as apps are tested)\n"
    (comp_dir / f"{name}.c").write_text(
        SHIM_TEMPLATE.format(name=name, quirks=quirk_lines), encoding="utf-8")
    (comp_dir / "CMakeLists.txt").write_text(
        CMAKE_TEMPLATE.format(name=name, kind="compat-shim"), encoding="utf-8")
    plan = {
        "kind": "compat-layer-plan",
        "module": module,
        "for_apps": apps,
        "quirks": q,
        "steps": [
            "reproduce the app failure in the VM; capture the exact error",
            "write the quirk into this shim with the app that unblocks it",
            "re-test the app in the VM; record PASS/FAIL in tests/",
            "keep shims tiny and per-quirk; never disable whole subsystems",
        ],
    }
    plan_path = comp_dir / "plan.json"
    jdump(plan, plan_path)
    return {"component": name, "c": str(comp_dir / f"{name}.c"), "plan": str(plan_path)}


def clone_reference_repo(workspace: str, repo: str = "reactos", dest: str | None = None,
                         depth: int = 1) -> dict:
    """Clone a reference implementation (ReactOS, Wine, ...) into third-party/ — read-only
    reference for patterns and specs; license headers of cloned code stay intact and
    cloned code is *never* shipped as part of the rebuild without license compliance."""
    ws = Path(workspace).expanduser().resolve()
    if not (ws / "workspace.json").exists():
        raise FileNotFoundError(f"not a workspace: {ws}")
    url = REFERENCE_REPOS.get(repo.lower(), repo)
    if not url.startswith(("http://", "https://", "git@")):
        raise ValueError(f"unknown reference repo '{repo}' and not a URL; known: "
                         f"{sorted(REFERENCE_REPOS)}")
    d = Path(dest) if dest else ws / "third-party" / repo.lower().replace("/", "-")
    if (d / ".git").exists():
        rc, out, err = run(["git", "-C", str(d), "pull", "--ff-only"], timeout=300)
        return {"repo": url, "path": str(d), "action": "pulled", "rc": rc,
                "output": (out + err).strip()[-1000:]}
    rc, out, err = run(["git", "clone", "--depth", str(depth), url, str(d)], timeout=1800)
    if rc != 0:
        raise RuntimeError(f"git clone failed rc={rc}: {(err or out).strip()[-1500:]}")
    return {"repo": url, "path": str(d.resolve()), "action": "cloned",
            "license_reminder": "cloned code is reference material; keep licenses intact and "
                                "never ship it as part of the rebuild output image"}


def build_plan(workspace: str, toolchain: str = "rosbe") -> dict:
    """Return the concrete build plan for this workspace (and check the host toolchain)."""
    ws = Path(workspace).expanduser().resolve()
    src = ws / "src"
    has_cmake = bool(which("cmake"))
    has_ninja = bool(which("ninja"))
    has_gcc_mingw = bool(which("x86_64-w64-mingw32-gcc")) or bool(which("i686-w64-mingw32-gcc"))
    steps = [
        "cd src && cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release"
        " -DCMAKE_TOOLCHAIN_FILE=<mingw-toolchain.cmake>",
        "cmake --build build",
        "package: build a bootable test image (grub/isolinux boot + your components)"
        " — full ReactOS build system is the reference for image assembly",
    ]
    return {
        "toolchain": toolchain,
        "host_checks": {"cmake": has_cmake, "ninja": has_ninja,
                        "mingw_gcc": has_gcc_mingw,
                        "reactos_be": bool(which("i386-pc-mingw32-gcc") or which("ninja"))},
        "steps": steps,
        "notes": [
            "ReactOS's own build (RosBE) is the reference flow: "
            "configure.sh + ninja bootcd — see third-party/reactos if cloned",
            "the rebuild targets MinGW/GCC (or MSVC-compatible C) — keep to C89/99 Win32",
            "build inside the workspace; never commit build outputs",
        ],
    }
