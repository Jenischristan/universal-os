"""uos — the universal-os CLI. Every MCP tool is callable from a shell too.

Groups: iso | vm | re | forge | test | kb | mcp. Each command has --help.
Docstrings in this file double as help text (universal-modder convention).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, knowledge as kb, qemu, retools, testtools, forgetools
from .util import split_guest_args, which


def _p(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _die(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


# ---------------------------------------------------------------- iso
def cmd_iso(args) -> int:
    if args.iso_cmd == "inspect":
        from . import isofs
        try:
            with isofs.IsoImage(args.path) as iso:
                _p({"volume_id": iso.volume_id, "joliet": iso.joliet,
                    "entries": iso.walk("/", depth=2, limit=args.limit)})
        except Exception as e:
            return _die(str(e))
    elif args.iso_cmd == "fingerprint":
        try:
            _p(retools.fingerprint_windows(args.path))
        except Exception as e:
            return _die(str(e))
    elif args.iso_cmd == "extract":
        try:
            _p(retools.iso_extract(args.path, args.member, args.out,
                                   max_bytes=args.max_mb * 1024 * 1024))
        except Exception as e:
            return _die(str(e))
    else:
        print("usage: uos iso inspect|fingerprint|extract <path>")
    return 0


# ---------------------------------------------------------------- vm
def cmd_vm(args) -> int:
    try:
        if args.vm_cmd == "create":
            _p(qemu.vm_create(args.name, args.iso, args.disk_gb, args.ram_mb, args.cpus,
                              args.workspace, args.network, args.force))
        elif args.vm_cmd == "boot":
            _p(qemu.vm_boot(args.name, args.wait, "d" if args.cd else "c"))
        elif args.vm_cmd == "list":
            _p({"vms": qemu.vm_list()})
        elif args.vm_cmd == "status":
            _p(qemu.vm_status(args.name))
        elif args.vm_cmd == "shot":
            _p(qemu.vm_screenshot(args.name, args.out))
        elif args.vm_cmd == "snapshot":
            _p(qemu.vm_snapshot(args.name, args.tag))
        elif args.vm_cmd == "restore":
            _p(qemu.vm_restore(args.name, args.tag))
        elif args.vm_cmd == "exec":
            # Windows-cmd semantics: backslashes stay literal, quotes group
            argv = split_guest_args(args.args) if args.args else []
            _p(qemu.vm_exec(args.name, args.path, argv, args.timeout))
        elif args.vm_cmd == "put":
            _p(qemu.vm_put_file(args.name, args.local, args.guest))
        elif args.vm_cmd == "get":
            _p(qemu.vm_get_file(args.name, args.guest, args.local))
        elif args.vm_cmd == "mount":
            _p(qemu.vm_mount_iso(args.name, args.iso))
        elif args.vm_cmd == "sendkey":
            _p(qemu.vm_sendkey(args.name, args.keys, args.hold_ms))
        elif args.vm_cmd == "network":
            _p(qemu.vm_network_config(args.name, args.enable))
        elif args.vm_cmd == "shutdown":
            _p(qemu.vm_shutdown(args.name, args.force))
        elif args.vm_cmd == "log":
            _p(qemu.vm_log(args.name, args.tail))
        elif args.vm_cmd == "destroy":
            _p(qemu.vm_destroy(args.name))
        else:
            print("unknown vm subcommand")
    except Exception as e:
        return _die(str(e))
    return 0


# ---------------------------------------------------------------- re
def cmd_re(args) -> int:
    try:
        if args.re_cmd == "fingerprint":
            _p(retools.fingerprint_windows(args.path))
        elif args.re_cmd == "pe":
            _p(retools.analyze_pe(args.path))
        elif args.re_cmd == "surface":
            _p(retools.dump_api_surface(args.src, args.out, args.pattern,
                                        args.include_exe, args.workspace))
        elif args.re_cmd == "trace":
            _p(retools.trace_syscalls(args.vm, args.workspace, args.app))
        elif args.re_cmd == "diff":
            _p(retools.behavior_diff(args.baseline, args.current, args.out,
                                     args.workspace))
        else:
            print("usage: uos re fingerprint|pe|surface|trace|diff ...")
    except Exception as e:
        return _die(str(e))
    return 0


# ---------------------------------------------------------------- forge
def cmd_forge(args) -> int:
    try:
        if args.forge_cmd == "init":
            _p(forgetools.init_workspace(args.path, args.name, args.iso, args.version,
                                         args.target))
        elif args.forge_cmd == "scaffold":
            exports = [e for e in (args.exports or "").split(",") if e.strip()]
            _p(forgetools.scaffold_component(args.workspace, args.name, args.kind,
                                             exports, args.note))
        elif args.forge_cmd == "stub":
            _p(forgetools.gen_api_stub(args.workspace, args.surface, args.module,
                                       args.max_stubs))
        elif args.forge_cmd == "shim":
            apps = [a for a in (args.apps or "").split(",") if a.strip()]
            quirks = [q for q in (args.quirks or "").split(";") if q.strip()]
            _p(forgetools.gen_compat_layer(args.workspace, args.module, apps, quirks))
        elif args.forge_cmd == "clone":
            _p(forgetools.clone_reference_repo(args.workspace, args.repo, args.dest))
        elif args.forge_cmd == "plan":
            _p(forgetools.build_plan(args.workspace, args.toolchain))
        elif args.forge_cmd == "status":
            _p(forgetools.workspace_status(args.workspace))
        elif args.forge_cmd == "cleanup":
            _p(forgetools.cleanup_workspace(args.workspace, args.confirm))
        else:
            print("usage: uos forge init|scaffold|stub|shim|clone|plan|status|cleanup ...")
    except Exception as e:
        return _die(str(e))
    return 0


# ---------------------------------------------------------------- test
def cmd_test(args) -> int:
    try:
        if args.test_cmd == "app":
            argv = split_guest_args(args.args or "")
            inst = split_guest_args(args.install) if args.install else None
            run = split_guest_args(args.run) if args.run else None
            _p(testtools.test_app_in_vm(args.vm, args.app, argv, args.workspace,
                                        inst, run, args.timeout, args.label))
        elif args.test_cmd == "report":
            _p(testtools.compat_report(args.workspace))
        elif args.test_cmd == "regress":
            _p(testtools.regression_log(args.workspace, args.status, args.note))
        else:
            print("usage: uos test app|report|regress ...")
    except Exception as e:
        return _die(str(e))
    return 0


# ---------------------------------------------------------------- kb
def cmd_kb(args) -> int:
    try:
        if args.kb_cmd == "search":
            _p({"hits": kb.search(args.query, limit=args.limit)})
        elif args.kb_cmd == "path":
            _p(kb.kb_path())
        elif args.kb_cmd == "new":
            _p(kb.new_note(args.os, args.component, args.title, args.agent,
                           args.status, args.tags, out=args.out))
        elif args.kb_cmd == "check":
            _p(kb.check_note(args.note))
        elif args.kb_cmd == "index":
            _p(kb.index())
        else:
            print("usage: uos kb search|path|new|check|index ...")
    except Exception as e:
        return _die(str(e))
    return 0


# ---------------------------------------------------------------- env/mcp
def cmd_env(args) -> int:
    kvm = Path("/dev/kvm").exists()
    _p({
        "version": __version__,
        "qemu": which("qemu-system-x86_64"),
        "qemu_img": which("qemu-img"),
        "git": which("git"),
        "cmake": which("cmake"),
        "ninja": which("ninja"),
        "mingw_x86_64": which("x86_64-w64-mingw32-gcc"),
        "mingw_i686": which("i686-w64-mingw32-gcc"),
        "kvm": kvm,
        "accel": "kvm" if kvm else "tcg (slow)",
    })
    return 0


def cmd_mcp(args) -> int:
    """Run the MCP server over stdio (same entry point as `uos-mcp`)."""
    from .mcp_server import main as mcp_main
    mcp_main()
    return 0


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="uos",
        description="universal-os — reverse engineer a Windows ISO in a sandbox VM and "
                    "rebuild it ReactOS-style, component by component, until its apps "
                    "run on the rebuild. See SKILL.md for the loop and RULES.md for the "
                    "guardrails.")
    ap.add_argument("--version", action="version", version=f"uos {__version__}")
    sub = ap.add_subparsers(dest="group", required=True)

    iso = sub.add_parser("iso", help="inspect install ISOs without mounting them")
    iso_sub = iso.add_subparsers(dest="iso_cmd", required=True)
    p = iso_sub.add_parser("inspect", help="list ISO contents (ISO9660/Joliet)")
    p.add_argument("path"); p.add_argument("--limit", type=int, default=300)
    p = iso_sub.add_parser("fingerprint", help="which Windows version is inside")
    p.add_argument("path")
    p = iso_sub.add_parser("extract",
                           help="extract one file from the ISO (inspect only, no mount)")
    p.add_argument("path"); p.add_argument("member", help="path inside the ISO, e.g. /I386/NTOSKRNL.EX_")
    p.add_argument("out", help="destination file or directory (keep it OUTSIDE the repo)")
    p.add_argument("--max-mb", type=int, default=64, help="extraction size cap in MiB")
    iso.set_defaults(func=cmd_iso)

    vm = sub.add_parser("vm", help="sandbox VM lifecycle (QEMU headless)")
    vm_sub = vm.add_subparsers(dest="vm_cmd", required=True)
    p = vm_sub.add_parser("create"); p.add_argument("name"); p.add_argument("iso")
    p.add_argument("--disk-gb", type=int, default=30)
    p.add_argument("--ram-mb", type=int, default=2048)
    p.add_argument("--cpus", type=int, default=2)
    p.add_argument("--workspace", default=None)
    p.add_argument("--network", action="store_true",
                   help="enable user-mode networking (ask the user first)")
    p.add_argument("--force", action="store_true")
    p = vm_sub.add_parser("boot"); p.add_argument("name")
    p.add_argument("--wait", type=int, default=45)
    p.add_argument("--cd", action="store_true", help="boot CD first (default) vs disk")
    p.set_defaults(cd=True)
    p = vm_sub.add_parser("list")
    p = vm_sub.add_parser("status"); p.add_argument("name")
    p = vm_sub.add_parser("shot"); p.add_argument("name"); p.add_argument("--out", default=None)
    p = vm_sub.add_parser("snapshot"); p.add_argument("name"); p.add_argument("tag")
    p = vm_sub.add_parser("restore"); p.add_argument("name"); p.add_argument("tag")
    p = vm_sub.add_parser("exec"); p.add_argument("name"); p.add_argument("path")
    p.add_argument("args", nargs="?", default=""); p.add_argument("--timeout", type=int, default=120)
    p = vm_sub.add_parser("put"); p.add_argument("name"); p.add_argument("local"); p.add_argument("guest")
    p = vm_sub.add_parser("get"); p.add_argument("name"); p.add_argument("guest"); p.add_argument("local")
    p = vm_sub.add_parser("mount"); p.add_argument("name"); p.add_argument("iso")
    p = vm_sub.add_parser("sendkey",
                          help="send a key combo to the display (drive installers pre-guest-agent)")
    p.add_argument("name"); p.add_argument("keys", help="e.g. ret, esc, f8, ctrl-alt-delete, shift-f10")
    p.add_argument("--hold-ms", type=int, default=100)
    p = vm_sub.add_parser("network",
                          help="show/set the VM's network flag (off by default; enabling needs the user's OK; NAT only)")
    p.add_argument("name")
    p.add_argument("--enable", action="store_true",
                   help="enable user-mode NAT networking (RULES.md: ask the user first)")
    p = vm_sub.add_parser("shutdown"); p.add_argument("name"); p.add_argument("--force", action="store_true")
    p = vm_sub.add_parser("log"); p.add_argument("name"); p.add_argument("--tail", type=int, default=80)
    p = vm_sub.add_parser("destroy"); p.add_argument("name")
    vm.set_defaults(func=cmd_vm)

    re_ = sub.add_parser("re", help="reverse engineering: fingerprints, PE, surfaces, traces")
    re_sub = re_.add_subparsers(dest="re_cmd", required=True)
    p = re_sub.add_parser("fingerprint"); p.add_argument("path")
    p = re_sub.add_parser("pe"); p.add_argument("path")
    p = re_sub.add_parser("surface"); p.add_argument("src"); p.add_argument("out")
    p.add_argument("--pattern", default="*.dll"); p.add_argument("--include-exe", action="store_true")
    p.add_argument("--workspace", default=None)
    p = re_sub.add_parser("trace")
    p.add_argument("--vm", default=None); p.add_argument("--workspace", default=None)
    p.add_argument("--app", default=None)
    p = re_sub.add_parser("diff"); p.add_argument("baseline"); p.add_argument("current")
    p.add_argument("--out", default=None); p.add_argument("--workspace", default=None)
    re_.set_defaults(func=cmd_re)

    fg = sub.add_parser("forge", help="rebuild: workspaces, scaffolds, stubs, shims, clones")
    fg_sub = fg.add_subparsers(dest="forge_cmd", required=True)
    p = fg_sub.add_parser("init"); p.add_argument("path")
    p.add_argument("--name", default=None); p.add_argument("--iso", default=None)
    p.add_argument("--version", default=None); p.add_argument("--target", default="windows-any")
    p = fg_sub.add_parser("scaffold"); p.add_argument("workspace"); p.add_argument("name")
    p.add_argument("--kind", default="win32dll"); p.add_argument("--exports", default="")
    p.add_argument("--note", default="")
    p = fg_sub.add_parser("stub"); p.add_argument("workspace"); p.add_argument("surface")
    p.add_argument("module"); p.add_argument("--max-stubs", type=int, default=64)
    p = fg_sub.add_parser("shim"); p.add_argument("workspace"); p.add_argument("module")
    p.add_argument("--apps", default=""); p.add_argument("--quirks", default="")
    p = fg_sub.add_parser("clone"); p.add_argument("workspace"); p.add_argument("--repo", default="reactos")
    p.add_argument("--dest", default=None)
    p = fg_sub.add_parser("plan"); p.add_argument("workspace")
    p.add_argument("--toolchain", default="rosbe")
    p = fg_sub.add_parser("status", help="workspace readiness: dirs, journal, api/ and src/ state")
    p.add_argument("workspace")
    p = fg_sub.add_parser("cleanup", help="find (and with --confirm delete) regenerable junk; dry run by default")
    p.add_argument("workspace"); p.add_argument("--confirm", action="store_true")
    fg.set_defaults(func=cmd_forge)

    te = sub.add_parser("test", help="app-compat testing in the VM")
    te_sub = te.add_subparsers(dest="test_cmd", required=True)
    p = te_sub.add_parser("app"); p.add_argument("vm")
    p.add_argument("app", nargs="?", default=None)
    p.add_argument("--args", default=""); p.add_argument("--workspace", default=None)
    p.add_argument("--install", default=""); p.add_argument("--run", default="")
    p.add_argument("--timeout", type=int, default=180); p.add_argument("--label", default=None)
    p = te_sub.add_parser("report"); p.add_argument("workspace")
    p = te_sub.add_parser("regress"); p.add_argument("workspace")
    p.add_argument("status"); p.add_argument("note")
    te.set_defaults(func=cmd_test)

    kbp = sub.add_parser("kb", help="field notes AIs write for AIs")
    kb_sub = kbp.add_subparsers(dest="kb_cmd", required=True)
    p = kb_sub.add_parser("search"); p.add_argument("query"); p.add_argument("--limit", type=int, default=10)
    p = kb_sub.add_parser("path", help="show which knowledge-base roots resolve (repo/package/UOS_HOME)")
    p = kb_sub.add_parser("new"); p.add_argument("--os", required=True)
    p.add_argument("--component", required=True); p.add_argument("--title", required=True)
    p.add_argument("--agent", default="ai-agent"); p.add_argument("--status", default="working")
    p.add_argument("--tags", default=""); p.add_argument("--out", default=None)
    p = kb_sub.add_parser("check"); p.add_argument("note")
    p = kb_sub.add_parser("index")
    kbp.set_defaults(func=cmd_kb)

    env = sub.add_parser("env", help="check host toolchain (qemu, git, cmake, mingw, kvm)")
    env.set_defaults(func=cmd_env)

    mcp_p = sub.add_parser("mcp", help="run the MCP server over stdio (== uos-mcp)")
    mcp_p.set_defaults(func=cmd_mcp)
    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
