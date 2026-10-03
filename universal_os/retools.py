"""Reverse-engineering tools: ISO fingerprinting, PE analysis, API-surface dumps,
syscall-trace plans, and behavioral diffing. All inspection, zero code lifting —
see RULES.md for what may and may not enter the rebuilt-OS repo.
"""
from __future__ import annotations

import fnmatch
import re
import time
from pathlib import Path

from . import isofs, pefile
from .util import jdump, jload, human_size

# ---------------------------------------------------------------------------
# ISO fingerprinting
# ---------------------------------------------------------------------------

KNOWN_MARKERS = {
    "I386/WIN51": "Windows XP (WIN51 markers)",
    "I386/WIN51IC": "Windows XP professional marker",
    "I386/WIN51IP": "Windows XP home marker",
    "I386/NTOSKRNL.EX_": "XP-era kernel payload (LZ compressed)",
    "I386/CDROM_NT.5": "NT 5.x (2000/XP/2003) install media",
    "I386/CDROM_NT.6": "NT 6.x install media",
    "SOURCES/INSTALL.WIM": "Windows Vista+ WIM install image",
    "SOURCES/INSTALL.ESD": "Windows 8+ ESD install image",
    "SOURCES/CVERSION.INI": "Vista+ setup version file",
    "SOURCES/SETUP.EXE": "Vista+ setup binary",
    "BOOT/BCD": "Vista+ boot configuration data",
    "BOOTMGR": "Vista+ boot manager",
    "SETUP.EXE": "root setup executable",
    "AUTORUN.INF": "autorun metadata",
    "WINNT32.EXE": "2000/XP 32-bit setup",
    "X64/SOURCES": "XP x64 / Server 2003 x64 layout",
    "SUPPORT/TOOLS": "support tools (usually contains versioned binaries)",
    "EFI/BOOT/BOOTX64.EFI": "UEFI boot stub",
}


def fingerprint_windows(iso_path: str) -> dict:
    """Identify which Windows (any version) an install ISO contains, without mounting."""
    with isofs.IsoImage(iso_path) as iso:
        listing = iso.walk("/", depth=2)
        paths = {e["path"].upper().rstrip("/") for e in listing}
        found = {}
        for marker, meaning in KNOWN_MARKERS.items():
            m = marker.upper()
            if any(p == m or p.startswith(m + "/") for p in paths):
                found[marker] = meaning

        result: dict = {
            "iso": str(Path(iso_path).resolve()),
            "iso_size": human_size(Path(iso_path).stat().st_size),
            "volume_id": iso.volume_id,
            "joliet": iso.joliet,
            "layout": "legacy (I386/)" if any(k.startswith("I386") for k in found)
                      else ("modern (SOURCES/WIM)" if any(k.startswith("SOURCES") for k in found) else "unknown"),
            "markers": found,
            "version_guess": None,
            "confidence": "low",
            "evidence": [],
        }

        # evidence source 1: cversion.ini (Vista+)
        try:
            cv = iso.read_file("/sources/cversion.ini", max_bytes=65536).decode(
                "utf-8", "replace")
            m = re.search(r"BuildInfo\s*=\s*.*?(\d{5,7})", cv)
            if m:
                result["evidence"].append(f"sources/cversion.ini build {m.group(1)}")
                result["confidence"] = "medium"
        except Exception:
            pass

        # evidence source 2: version resources of a small setup binary
        for candidate in ("/setup.exe", "/sources/setup.exe", "/i386/winnt32.exe",
                          "/winnt32.exe", "/i386/setup.exe"):
            try:
                blob = iso.read_file(candidate, max_bytes=8 * 1024 * 1024)
            except Exception:
                continue
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as tf:
                tf.write(blob)
                tmp = tf.name
            try:
                pe = pefile.parse_pe(tmp)
                ver = pefile.version_from_strings(pe.get("version_strings", {}))
                product = pe.get("version_strings", {}).get("productname", "")
                if ver:
                    nt = tuple(int(x) for x in ver.split("."))
                    result["version_guess"] = {
                        "pe_version": ver,
                        "windows": pefile.guess_windows(nt),
                        "source_file": candidate,
                        "subsystem": pe["subsystem"],
                        "product_name": product,
                    }
                    result["confidence"] = "high" if product else "medium"
                    result["evidence"].append(f"{candidate} version resource = {ver}")
                    break
            except Exception:
                continue
            finally:
                Path(tmp).unlink(missing_ok=True)

        # evidence source 3: WINNT/CDROM marker files naming the NT version
        for marker_file in ("/i386/cdrom_nt.5", "/i386/cdrom_nt.6"):
            try:
                iso.read_file(marker_file, max_bytes=1024)
                result["evidence"].append(f"{marker_file} present -> NT "
                                          f"{'5.x (2000/XP/2003)' if '.5' in marker_file else '6.x (Vista+ legacy path)'}")
                if result["confidence"] == "low":
                    result["confidence"] = "medium"
            except Exception:
                pass

        result["top_level"] = iso.listdir("/", limit=100)
        result["note"] = (
            "Version resources of setup binaries are interface facts (allowed to keep). "
            "Do not copy media contents into the workspace; extract only specs."
        )
        return result


# ---------------------------------------------------------------------------
# PE analysis
# ---------------------------------------------------------------------------

def analyze_pe(path: str) -> dict:
    pe = pefile.parse_pe(path)
    pe["summary"] = {
        "module": Path(path).name,
        "bits": pe["bits"],
        "machine": pe["machine"],
        "subsystem": pe["subsystem"],
        "is_dll": pe["is_dll"],
        "os_version": pe["os_version"],
        "exports": pe["exports"]["n_names"] if pe.get("exports") else 0,
        "import_dlls": len(pe.get("imports", [])),
    }
    if pe.get("version_strings"):
        pe["summary"]["product"] = pe["version_strings"].get("productname", "")
        pe["summary"]["version"] = pefile.version_from_strings(pe["version_strings"])
    return pe


# ---------------------------------------------------------------------------
# API surface dumps
# ---------------------------------------------------------------------------

def _should_skip(name: str, patterns: list[str] | None, exclude: list[str]) -> bool:
    if patterns and not any(fnmatch.fnmatch(name.lower(), p.lower()) for p in patterns):
        return True
    return any(fnmatch.fnmatch(name.lower(), x.lower()) for x in exclude)


def dump_api_surface(src_dir: str, out: str, pattern: str = "*.dll",
                     include_exe: bool = False, workspace: str | None = None) -> dict:
    """Walk a directory of Windows DLLs (an inspected copy OUTSIDE the repo) and record
    their interface facts: export names, ordinals, import needs, versions.

    Interface facts (names/ordinals/versions) are fine to keep; binary content and
    decompiled bodies are not (RULES.md)."""
    src = Path(src_dir).expanduser().resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"not a directory: {src}")
    modules = []
    pats = [pattern] + (["*.exe"] if include_exe else [])
    files = sorted(p for p in src.rglob("*") if p.is_file())
    for f in files:
        if _should_skip(f.name, pats, exclude=[]):
            continue
        try:
            pe = pefile.parse_pe(f)
        except Exception as e:
            modules.append({"module": f.name, "path": str(f), "error": str(e)})
            continue
        modules.append({
            "module": f.name,
            "path": str(f),
            "bits": pe["bits"],
            "machine": pe["machine"],
            "subsystem": pe["subsystem"],
            "os_version": pe["os_version"],
            "version": pefile.version_from_strings(pe.get("version_strings", {})),
            "product": pe.get("version_strings", {}).get("productname", ""),
            "exports": (pe.get("exports") or {}).get("names", []),
            "n_exports": (pe.get("exports") or {}).get("n_names", 0),
            "imports": {imp["dll"]: imp["functions"] for imp in pe.get("imports", [])},
        })
    surface = {
        "kind": "api-surface",
        "source_dir": str(src),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tool": "universal-os",
        "module_count": len(modules),
        "total_exports": sum(m.get("n_exports", 0) for m in modules),
        "modules": modules,
    }
    out_path = jdump(surface, Path(out).expanduser().resolve() if not Path(out).is_absolute()
                     else Path(out))

    md = Path(out_path).with_suffix(".md")
    lines = [
        f"# API surface — {src.name}",
        "",
        f"Generated {surface['generated']} from `{src}` ({len(modules)} modules, "
        f"{surface['total_exports']} exports). Interface facts only.",
        "",
        "| Module | Bits | Exports | Version | Product |",
        "|---|---|---|---|---|",
    ]
    for m in modules[:200]:
        lines.append(f"| {m.get('module')} | {m.get('bits', '?')} | {m.get('n_exports', 0)} "
                     f"| {m.get('version') or '?'} | {m.get('product') or ''} |")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if workspace:
        _register_artifact(workspace, "api_surfaces", str(out_path))
    return {"json": str(out_path), "markdown": str(md), "modules": len(modules),
            "total_exports": surface["total_exports"]}


def _register_artifact(workspace: str, kind: str, path: str) -> None:
    ws = Path(workspace).expanduser().resolve()
    cfg_p = ws / "workspace.json"
    if not cfg_p.exists():
        return
    try:
        cfg = jload(cfg_p)
    except Exception:
        return
    cfg.setdefault("artifacts", {}).setdefault(kind, []).append(
        {"path": path, "when": time.strftime("%Y-%m-%d %H:%M:%S")})
    jdump(cfg, cfg_p)


# ---------------------------------------------------------------------------
# Trace plans
# ---------------------------------------------------------------------------

def trace_syscalls(vm: str | None = None, workspace: str | None = None,
                   target_app: str | None = None, out: str | None = None) -> dict:
    """Produce a concrete NT-syscall/API trace plan for the running VM.

    Honest scope: real NT syscall capture inside a Windows guest needs in-guest tooling
    (ETW/xperf/WPR, or a kernel debugger over KDNET). This tool writes the exact plan +
    commands into the workspace and can kick off in-guest tracing via the guest agent."""
    plan = {
        "kind": "trace-plan",
        "vm": vm,
        "target_app": target_app,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "methods": [
            {
                "name": "ETW/WPR (in-guest, no kernel debugger needed)",
                "steps": [
                    "1. vm_exec: cmd /c wpr -start GeneralProfile -filemode",
                    "2. run the target app (vm_exec or manually in the VM display)",
                    "3. vm_exec: cmd /c wpr -stop C:\\trace\\app.etl",
                    "4. vm_get_file C:\\trace\\app.etl out of the VM",
                    "5. analyze offline: xperf -i app.etl -o symbols.csv (or WPA)",
                ],
                "gives": "user-mode API call volumes, stacks with symbols after stepping",
            },
            {
                "name": "KDNET kernel debugging (deep, needs a second network endpoint)",
                "steps": [
                    "guest (admin): bcdedit /debug on",
                    "guest: bcdedit /dbgsettings net hostip:<host-ip> port:50000 key:1.2.3.4",
                    "host: kd -k net:port=50000,key=1.2.3.4 -y <srvr-symbols>",
                    "set breakpoints on nt!Nt* of interest",
                ],
                "gives": "exact syscall sequences and arguments",
            },
            {
                "name": "Import + version static view (this toolkit)",
                "steps": [
                    "dump_api_surface on the inspected DLL directory",
                    "behavior_diff against the rebuilt build's surface",
                ],
                "gives": "interface coverage metrics without dynamic tracing",
            },
        ],
    }
    if vm:
        from . import qemu
        try:
            ga_plan = qemu.vm_exec(vm, "cmd.exe", ["/c", "mkdir C:\\trace 2>nul"], timeout=30)
            plan["guest_prep"] = ga_plan
        except Exception as e:
            plan["guest_prep_error"] = str(e)
    dest = Path(out) if out else None
    if workspace and not dest:
        dest = Path(workspace).expanduser().resolve() / "spec" / f"trace-plan-{time.strftime('%Y%m%d-%H%M%S')}.json"
    result = {"plan": plan}
    if dest:
        jdump(plan, dest)
        result["plan_file"] = str(dest)
    return result


# ---------------------------------------------------------------------------
# Behavior diff
# ---------------------------------------------------------------------------

def behavior_diff(baseline: str, current: str, out: str | None = None,
                  workspace: str | None = None) -> dict:
    """Compare two API-surface dumps: what the reference exposes vs what the rebuild exposes."""
    base = jload(Path(baseline))
    cur = jload(Path(current))

    def index(surface: dict) -> dict[str, set[str]]:
        idx: dict[str, set[str]] = {}
        for m in surface.get("modules", []):
            name = m.get("module", "?").lower()
            idx.setdefault(name, set()).update(m.get("exports") or [])
        return idx

    bi, ci = index(base), index(cur)
    all_modules = sorted(set(bi) | set(ci))
    rows = []
    total_missing = total_extra = 0
    for mod in all_modules:
        b, c = bi.get(mod, set()), ci.get(mod, set())
        missing = sorted(b - c)
        extra = sorted(c - b)
        total_missing += len(missing)
        total_extra += len(extra)
        rows.append({
            "module": mod,
            "reference_exports": len(b),
            "rebuild_exports": len(c),
            "missing_in_rebuild": missing,
            "extra_in_rebuild": extra,
            "coverage": round(len(b & c) / len(b) * 100, 2) if b else None,
        })
    covered = [r for r in rows if r["coverage"] is not None]
    overall = (round(sum(r["coverage"] for r in covered) / len(covered), 2)
               if covered else None)
    report = {
        "kind": "behavior-diff",
        "baseline": baseline,
        "current": current,
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "overall_coverage_pct": overall,
        "total_missing_in_rebuild": total_missing,
        "total_extra_in_rebuild": total_extra,
        "modules": rows,
    }
    res = {"summary": {k: report[k] for k in
                       ("overall_coverage_pct", "total_missing_in_rebuild", "total_extra_in_rebuild")},
           "worst_modules": sorted(
               [r for r in rows if r["coverage"] is not None],
               key=lambda r: r["coverage"])[:10]}
    if out or workspace:
        dest = Path(out) if out else (Path(workspace).expanduser().resolve()
                                      / "reports" / f"behavior-diff-{time.strftime('%Y%m%d-%H%M%S')}.json")
        jdump(report, dest)
        md = dest.with_suffix(".md")
        lines = [
            f"# Behavior diff — {time.strftime('%F %T')}",
            "",
            f"Baseline `{baseline}` vs rebuild `{current}`",
            f"Overall interface coverage: **{overall}%** "
            f"({total_missing} missing exports, {total_extra} extras)",
            "",
            "| Module | Ref | Rebuild | Coverage | Missing (first 15) |",
            "|---|---|---|---|---|",
        ]
        for r in rows[:100]:
            cov = f"{r['coverage']}%" if r["coverage"] is not None else "—"
            lines.append(f"| {r['module']} | {r['reference_exports']} | {r['rebuild_exports']} "
                         f"| {cov} | {', '.join(r['missing_in_rebuild'][:15]) or '—'} |")
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        res["json"] = str(dest)
        res["markdown"] = str(md)
    return res
