---
name: build-any-os
description: Reverse engineer an existing operating system from an ISO and rebuild it ReactOS-style, component by component, until apps written for the original OS run on the rebuild. Use when the user wants to recreate, clone, reimplement or rebuild an OS ("rebuild this Windows XP ISO ReactOS-style", "make an OS that can run Windows apps", "reverse engineer this ISO", "why won't my rebuilt build run notepad"). Covers ISO fingerprinting, sandbox VM labs, API-surface surveys, behavioral specs, clean-room component scaffolding, builds, in-VM app testing and knowledge-base notes.
---

# Build any OS

> Canonical copy: `skills/build-any-os/SKILL.md` (Agent Skills format). This root mirror is
> what agents read first when opened at the repo top level — keep both in sync when editing.

You are the rebuilder. The user names an ISO and a compatibility goal ("run notepad and cmd",
"run this app"), and you take it all the way to that app running on the rebuilt OS. The method
is the ReactOS/Wine method — clean-room reimplementation from behavioral specs — with the loop,
tools and guardrails of this repo doing the driving.

- Guardrails: `RULES.md` (read it before the first tool call; the short form is below).
- Phase playbooks: `skills/build-any-os/references/` — one per phase of the loop.
- Worked example: `examples/first-rebuild/EXAMPLE.md`.
- Everything other agents wrote down: the knowledge base (`knowledge/`, `uos kb search`, `uos kb path`).

## What "the rebuild" is

A workspace (`uos forge init`) containing clean-room C sources in ReactOS layout
(`src/{boot,drivers,subsystems,dll,shell}`), `.spec` export tables generated from real API
surfaces, behavioral specs in `spec/`, app-compat results in `tests/`, and reference clones in
`third-party/`. The rebuild is measured in **interface coverage** (`behavior_diff`) and
**app pass rate** (`test_app_in_vm` + `compat_report`) — not in vibes.

## Your tools

`uos-mcp` is the MCP server; `uos` is the same CLI. Every command has `--help`.

| Need | Tool |
|---|---|
| Check what the host can do (qemu, kvm, git, cmake, mingw) | `env_check` |
| What Windows is inside this ISO, without booting it | `fingerprint_windows`, `iso_inspect` |
| A sandbox lab: create, boot, screenshot, snapshot, restore | `vm_create` → `vm_boot` → `vm_screenshot` → `vm_snapshot`/`vm_restore` |
| Drive the guest (needs qemu-ga installed in it) | `vm_exec`, `vm_put_file`, `vm_get_file`, `vm_mount_iso` |
| Drive the installer BEFORE the guest agent exists | `vm_sendkey` (+ `vm_screenshot` after each) |
| One binary's interface facts (headers, imports, exports, versions) | `analyze_pe` |
| Pull one file out of the ISO without booting or mounting | `iso_extract` |
| A whole directory of reference DLLs → the target contract | `dump_api_surface` |
| How to capture syscalls in-guest (ETW/WPR, KDNET) | `trace_syscalls` |
| Reference vs rebuild: who exports what, coverage % | `behavior_diff` |
| The rebuild's skeleton: workspace, components, stubs, shims | `init_workspace`, `scaffold_component`, `gen_api_stub`, `gen_compat_layer` |
| Prior art: ReactOS, Wine, QEMU, virtio-win | `clone_reference_repo` |
| How to build what the host allows | `build_plan` |
| Does the app actually run on the rebuild? | `test_app_in_vm` → `compat_report` → `regression_log` |
| What previous agents learned | `kb_search`, `kb_new`, `kb_check`, `kb_index`, `kb_path` |

## The loop

### 0. Intake (keep it short)
- Get the ISO path, the compatibility goal in one sentence ("notepad + cmd + our inventory
  app"), and what "done" means. Agree the guardrail level (`RULES.md` defaults to moderate).
- Start `WORKSPACE.md` (`uos forge init` creates it). Record paths, versions, interface facts,
  failures, next step. Anything not journaled is lost at the next context compaction.
- If the ISO is not the user's own legal copy, stop and say so. This toolkit never handles
  pirated media, and never touches activation, DRM or licensing.

### 1. Recon
- **Knowledge base first.** `kb_search "<os>"`, `kb_search "<component>"`. If a field note
  exists, start from its exact versions, route and gotchas, and don't repeat its dead ends.
- `env_check`. If QEMU is missing, tell the user the one command to install it; don't improvise
  around the sandbox.
- `fingerprint_windows <iso>`: version, build, layout (I386/ vs SOURCES/WIM), confidence.
  The version decides the API-surface strategy — NT 5.x (XP/2003) and NT 6.x (Vista+) differ
  enormously. `iso_inspect` for the file layout when the fingerprint is ambiguous.
- Read the matching phase playbook in `skills/build-any-os/references/` before the first VM boot.

### 2. Lab (the safety net)
- `vm_create` with the reference ISO: network **off**, disk sized to the OS (XP: 8-10 GB is
  plenty; Win10: 40+ GB), then `vm_boot` and `vm_screenshot` in a loop to walk the installer.
  Text-mode setup screens that need a keypress: `vm_sendkey` (`ret`, `f8`, `spc`, ...) —
  screenshot after each combo to see the installer react.
- Under TCG (no `/dev/kvm`) a full Windows install takes 30-90+ minutes — say so up front,
  snapshot at milestones (`vm_snapshot` right after a clean install: `clean-install`), and
  prefer restoring snapshots to reinstalling.
- The rebuilt OS gets its **own** VM and disk later (phase: verify). One lab per purpose,
  snapshots between risky steps. `vm_shutdown` cleanly; force only when wedged.

### 3. Survey (read the real thing, don't guess)
- In the reference VM: install the QEMU guest agent, then `vm_exec` works and `vm_get_file`
  can pull artifacts out. The default route needs **no networking**: swap in a virtio-win ISO
  with `vm_mount_iso`, install qemu-ga from it (with `vm_sendkey`/screenshots through the
  installer, or its silent MSI switch via `vm_exec` once it is running), then swap the
  reference ISO back. Only fetch the MSI from the network inside the guest if the user has
  explicitly approved VM networking for this VM (RULES.md §6).
- `dump_api_surface` the reference system DLLs (extract copies **outside** the repo, e.g.
  `~/inspect/<os>/`; only the generated surface JSON/MD enters `api/`). The surface is the
  rebuild's target contract: module → exports → imports → versions.
- `trace_syscalls` writes the in-guest trace plan (WPR/ETW first, KDNET when the user agrees
  to a debug setup). Run traces per app in the goal; journal the observed behavior in `spec/`.
- `analyze_pe` individual binaries when a component's version resource or import set matters.
- Everything you learn lands in `spec/` as a behavioral spec (inputs → expected outputs,
  error codes, side effects) and in `WORKSPACE.md` as one-line facts.

### 4. Route (cheapest path to the goal)

| Route | When |
|---|---|
| Reuse ReactOS component wholesale | the component exists upstream, license-compatible, and the goal only needs it present |
| Implement missing exports on a ReactOS base | component exists but the app needs more of it — `gen_api_stub` on the diff |
| Standalone clean-room component | no upstream match — `scaffold_component` and implement from `spec/` |
| Compat shim | app-specific quirk — `gen_compat_layer`, one quirk per app, never subsystem-wide hacks |

- `clone_reference_repo` (ReactOS first, Wine for user-mode behavior, QEMU/virtio-win for the
  lab). Cloned code is **reference material**: read it, cite it, never ship it in the rebuild's
  image without license compliance, and never paste it as if it were your work.
- Order components by what the goal app imports: usually ntdll → kernel32 → user32/gdi32 →
  advapi32 → msvcrt → the app's oddballs. Write the chosen route into `WORKSPACE.md` first.

### 5. Spec before code
- For every export you are about to implement: one behavioral spec entry in `spec/<module>.md`
  — signature (from the surface dump), documented behavior, error paths, and how you will
  verify it. Interface facts come from the dump; behavior comes from documentation plus
  observed traces. If you cannot state the behavior, trace it — don't invent it.
- Decompiled output stays outside the repo. Reading it to understand behavior is allowed at the
  moderate guardrail level; **copying it into `src/`, `spec/`, tests, notes or reports is not**.

### 6. Build one working slice
- `scaffold_component` / `gen_api_stub` → fill specs → implement the minimum exports the goal
  app needs → `build_plan` and compile (RosBE-style MinGW or MSVC-compatible C).
- Prefer ReactOS idioms: `.spec` export tables, `WINAPI` calling conventions, W-suffix APIs
  implemented over their Nt/Zw cores, small DLLs, no surprises.
- Compile clean at `-Wall -Werror` where possible; a rebuilt OS is debugged enough already.

### 7. Verify on the metal
- Boot the rebuilt image in its own VM (`vm_create` + `vm_boot`, CD-first). `vm_screenshot`
  is your eyes; journal each milestone.
- `test_app_in_vm` with the goal app(s): copy in, install, run, capture exit/output/screenshot.
  Record PASS/FAIL per app in `tests/RESULTS.md`; `compat_report` aggregates; `regression_log`
  whenever a previously passing app breaks.
- `behavior_diff` the rebuild's surface against the reference surface — the coverage delta is
  your progress metric and your next-work queue.

### 8. Iterate
One component, one app, one quirk at a time. After each cycle: snapshot or restore, journal,
re-run the failing app first. Resist implementing exports nobody calls "for completeness" —
coverage only counts when a real app uses it.

### 9. Field note (leave the campsite cleaner)
- `kb_new --os <os> --component <component> --title "<what this milestone was>"`, fill every
  section (route, behavior learned, verification, gotchas as symptom → cause → fix), `kb_check`,
  `kb_index`, update the phase checkboxes in `WORKSPACE.md`. With your human's OK, PR it.

## Hard rules (short form — full text in `RULES.md`)
- Sandbox VM for everything untrusted; never mount the ISO or run its binaries on the host.
- Interface facts and behavioral specs may enter the repo; Microsoft binaries, decompiled code
  and media links may not — not in `src/`, not in `spec/`, not in notes.
- VM networking off by default; ask first. Never upload ISOs, dumps or traces.
- No activation/DRM/licensing work. No pirate media.
- Snapshot before risky steps; restore to undo; ask before deleting anything.
- Journal everything in `WORKSPACE.md` as you go.
