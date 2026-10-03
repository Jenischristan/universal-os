# TOOLS.md — every tool, what it does, when to call it

`uos-mcp` exposes 39 MCP tools over stdio; the `uos` CLI calls the same implementations.
Arguments are JSON types in MCP (strings for enums like `boot`). All paths accept `~`.
Errors are JSON `{"error": ...}` with actionable hints — read them, don't retry blind.

## Meta

| Tool | Args | Returns / notes |
|---|---|---|
| `env_check` | — | qemu, qemu-img, git, cmake, ninja, mingw, KVM presence + install hint. **Call once per session, first.** |
| `kb_search` | query, limit | field notes matching, best first. **Call before starting anything.** |
| `kb_new` / `kb_check` / `kb_index` | see `--help` | create / lint / index field notes (`knowledge/README.md`) |
| `kb_path` | — | which knowledge-base roots resolve (repo / packaged seed / UOS_HOME) — use when `kb_search` is empty and you need to know why |

## ISO & VM control

| Tool | Args | Notes |
|---|---|---|
| `iso_inspect` | iso_path, max_entries | pure ISO9660/Joliet read, **no mounting**. Layout + markers. |
| `iso_verify` | iso_path | pre-flight check: media readable, boot/install structure present (`/I386/` or `/SOURCES/`). Run after download, before `vm_create`. |
| `iso_extract` | iso_path, member, dest, max_mb | pull ONE file out of the ISO (no mount, no boot) into the inspect dir. Keep extracted copies outside the repo. |
| `fingerprint_windows` | iso_path | version/build guess + confidence + evidence. Decides the API strategy (NT 5.x vs 6.x). |
| `vm_create` | name, iso_path, disk_gb, ram_mb, cpus, workspace, network, force | registers a VM + qcow2 disk. network=false unless the user said yes. |
| `vm_boot` | name, wait_seconds, boot | headless start, boot="d" CD-first / "c" disk. TCG is slow — warn the user. |
| `vm_status` / `vm_list` | name? | running? qemu state? snapshots? |
| `vm_screenshot` | name | PNG path of the display. **The AI's eyes** — use after every boot/setup step. |
| `vm_snapshot` / `vm_restore` | name, tag | internal qcow2 snapshots. Snapshot before risk; restore to undo. |
| `vm_exec` | name, path, args, timeout | run a command in-guest via qemu-ga (install the agent first — error explains how). |
| `vm_put_file` / `vm_get_file` | name, local/guest paths | copy files host↔guest via qemu-ga. |
| `vm_mount_iso` | name, iso_path | swap the CD medium in a running VM (virtio-win ↔ reference ISO). |
| `vm_sendkey` | name, keys, hold_ms | key combo to the display (`ret`, `f8`, `ctrl-alt-delete`…). Drives text-mode installers **before** the guest agent exists. Screenshot after each. |
| `vm_network_config` | name, enable, nat | set the network flag (off by default; enabling needs the user's OK — RULES.md). NAT only; bridge raises. Applies at the next `vm_boot`. CLI: `uos vm network`. |
| `vm_shutdown` | name, force | ACPI powerdown → fallback quit → force kill. |
| `vm_log` | name, tail | serial console tail + the exact qemu command line. |

## Reverse engineering

| Tool | Args | Notes |
|---|---|---|
| `analyze_pe` | path | headers, sections, imports, exports, version resource. Interface facts only. |
| `dump_api_surface` | src_dir, out, pattern, include_exe, workspace | a directory of reference DLLs → the target contract (JSON + MD). Inspected copies stay outside the repo. |
| `trace_syscalls` | vm, workspace, target_app | writes the concrete in-guest tracing plan (WPR/ETW, KDNET) + optional guest prep. Dynamic tracing needs in-guest tooling — the plan says exactly what to run. |
| `behavior_diff` | baseline, current, out, workspace | reference surface vs rebuild surface: per-module coverage %, missing/extra exports. **The progress metric.** |

## OS reconstruction

| Tool | Args | Notes |
|---|---|---|
| `init_workspace` | path, name, iso, version, target | creates the rebuild workspace + `WORKSPACE.md` journal. |
| `scaffold_component` | workspace, name, kind, exports, behavior_note | ReactOS-style component: CMakeLists, `.spec`, `.c`, README, test. |
| `gen_api_stub` | workspace, surface_json, module, max_stubs | `.spec` + `E_NOTIMPL` stubs from a surface dump. Implement from specs, top-imports first. |
| `gen_compat_layer` | workspace, module, for_apps, quirks | small per-quirk shim; one quirk per app, never subsystem-wide. |
| `clone_reference_repo` | workspace, repo, dest | reactos / wine / qemu / virtio-win / any git URL → `third-party/` (reference only). |
| `build_plan` | workspace, toolchain | host toolchain check + exact build steps. |
| `workspace_status` | workspace | readiness report: required dirs, WORKSPACE.md journal + last line, api/ files, src/ components. CLI: `uos forge status`. |
| `cleanup_workspace` | workspace, confirm | find (and with `confirm=true` delete) regenerable junk: `__pycache__`, `.pytest_cache`, `build/`, `dist/`, `*.pyc`. Dry run by default; sources, journal, reports, third-party/ and VMs are never touched. CLI: `uos forge cleanup`. |

## Test harness

| Tool | Args | Notes |
|---|---|---|
| `test_app_in_vm` | vm, app_path, args, install_cmd, run_cmd, workspace, timeout, label | copy app in → install → run → capture exit/output/screenshot → PASS/FAIL recorded to `tests/results/` + `RESULTS.md`. |
| `compat_report` | workspace | aggregate: pass rate, failing labels, next-step guidance → `reports/`. |
| `regression_log` | workspace, status, note | append to `tests/REGRESSIONS.md` (pass/regressed/fixed/wip). |

## Typical session order

```
env_check → kb_search → iso_inspect → fingerprint_windows
→ vm_create → vm_boot → vm_screenshot (loop) → vm_snapshot
→ vm_mount_iso (agent) → vm_exec / vm_put_file / vm_get_file
→ dump_api_surface → trace_syscalls → analyze_pe
→ init_workspace → clone_reference_repo
→ behavior_diff (work queue) → scaffold_component / gen_api_stub
   → build_plan → build
→ vm_create (rebuild) → vm_boot → test_app_in_vm (loop)
→ compat_report → regression_log → behavior_diff
→ kb_new → kb_check → kb_index
```

MCP prompts mirror the phases: `start_rebuild`, `fingerprint`, `boot_and_install`,
`survey_apis`, `scaffold_and_build`, `test_app`, `field_note`.
