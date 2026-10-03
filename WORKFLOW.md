# WORKFLOW.md — one full rebuild, end to end

A concrete walkthrough of the loop from `SKILL.md`, using a realistic goal: **rebuild enough
of a Windows XP SP3 ISO that `notepad.exe` and `cmd.exe` run on the rebuilt build**. Commands
are shown as `uos ...` (CLI) — from an MCP client, call the same-named tool with the same
arguments. Adapt paths and versions to your session; the shape is what matters.

## Phase 0 — Intake

```
User: rebuild this XP ISO far enough to run notepad and cmd. ISO: ~/isos/xp-sp3.iso
```

- Goal: notepad + cmd on the rebuild. Done means: both launch, open/save works in notepad,
  `dir` and `cd` work in cmd.
- Guardrails: moderate (`RULES.md`).
- Journal started — see next phase.

## Phase 1 — Recon

```bash
uos kb search "windows xp rebuild"        # prior art first
uos kb search "ntdll"
uos env                                   # qemu? kvm? mingw? — what can this host do
uos iso fingerprint ~/isos/xp-sp3.iso
```

Typical result: `5.1.2600` from setup.exe's version resource (confidence: high), legacy
`I386/` layout → **NT 5.x strategy**: ReactOS is literally built for this surface; the route
is "ReactOS base + missing exports".

Journal:

```markdown
### 2026-10-03
- ISO: XP SP3 EN, build 2600, I386/ layout (fingerprint confidence: high)
- Host: qemu 8.2, no KVM (TCG — installs will be slow), mingw present
- Route (pending survey): ReactOS base, fill gaps toward notepad/cmd
```

## Phase 2 — Lab

```bash
uos vm create ref-os ~/isos/xp-sp3.iso --disk-gb 10 --ram-mb 1024 --cpus 2
uos vm boot ref-os --wait 60
uos vm shot ref-os            # read the PNG: BIOS? setup text? blue screen of what?
# ... walk the installer: screenshot after every step; partition, format, reboot on request
uos vm snapshot ref-os clean-install
```

- Under TCG expect 30-90 min for the XP install. Walk it with screenshots; text-mode setup
  needs you to press F6/Enter at the right times — `vm_exec` can't help before the guest agent
  exists, so it is screenshots + `vm_sendkey`-style patience (or do the keypresses by hand
  when you sit with the user).
- The moment XP reaches a desktop, snapshot `clean-install`. Everything risky reverts here.

## Phase 3 — Survey

```bash
# guest agent (one-time): mount virtio-win, install, mount the reference ISO back
uos vm mount ref-os ~/isos/virtio-win.iso
uos vm exec ref-os "cmd.exe" "/c d:\virtio-win-gt-x64.exe /quiet"   # or the qemu-ga MSI
uos vm mount ref-os ~/isos/xp-sp3.iso
uos vm exec ref-os "cmd.exe" "/c mkdir C:\uos-inspect" 2>/dev/null || true
```

Pull interface facts out:

```bash
# copy the core DLLs out of the guest for inspection (inspect dir is OUTSIDE the repo)
uos vm exec ref-os "cmd.exe" "/c copy C:\Windows\System32\ntdll.dll C:\uos-inspect\"
uos vm get ref-os "C:\uos-inspect\ntdll.dll" ~/inspect/xp/ntdll.dll
# ... repeat for kernel32, user32, gdi32, advapi32, msvcrt

uos re surface ~/inspect/xp ~/os-forge/api/xp-core-surface.json --workspace ~/os-forge
uos re trace --vm ref-os --workspace ~/os-forge --app notepad.exe
uos re pe ~/inspect/xp/ntdll.dll        # one binary's headers, imports, exports
```

- `trace_syscalls` gives the WPR/ETW steps; run them in-guest, pull the `.etl` back with
  `vm_get_file`, and write what notepad actually calls into `spec/`.
- The surface JSON is the **target contract**. Journal the headline numbers:

```markdown
- XP core surface: 5 modules, 2341 exports (ntdll 1419, kernel32 823, ...)
- notepad trace: heavy on NtCreateFile/NtReadFile + USER32 window/msg APIs; needs gdi32 fonts
```

## Phase 4 — Route

```bash
uos forge clone ~/os-forge --repo reactos      # the base: license-compatible, NT 5.x native
uos forge clone ~/os-forge --repo wine         # user-mode behavior reference
uos re diff ~/os-forge/api/xp-core-surface.json <reactos-surface-if-dumped>
```

- Compare the XP surface against what the ReactOS tree already provides (build ReactOS once,
  dump *its* surface with the same `re surface`, diff). The diff output **is** the work queue:
  per-module coverage % and missing exports, sorted worst-first.
- Decide per module: reuse upstream, extend upstream (`forge stub`), stand-alone scaffold, or
  shim. Journal the route before building.

## Phase 5 — Spec

For each export notepad actually needs, one spec entry in `~/os-forge/spec/ntdll.md`:

```markdown
### NtOpenFile
- signature (from surface): NTSTATUS NtOpenFile(PHANDLE, ACCESS_MASK, POBJECT_ATTRIBUTES,
  PIO_STATUS_BLOCK, ULONG, ULONG)
- behavior: opens by NT path; STATUS_OBJECT_NAME_NOT_FOUND on missing; sharing violations
  per sharing mode; (verify each claim against docs + the WPR trace, not from memory)
- verify: rosautotest NtOpenFile suite + notepad open/save round trip in the rebuild VM
```

No spec, no implementation. If docs + trace can't pin the behavior, trace again — don't guess.

## Phase 6 — Build a slice

```bash
uos forge scaffold ~/os-forge kernel32_lite --exports CreateFileW,ReadFile,WriteFile,CloseHandle
# fill specs; implement; then:
uos forge plan ~/os-forge      # host toolchain check + exact build steps
cd ~/os-forge/src && cmake -S . -B build -G Ninja && cmake --build build
```

ReactOS idioms: `.spec` export tables, W-over-Nt layering, `WINAPI`, small DLLs. Compile clean;
the rebuilt OS is debugged enough already.

## Phase 7 — Verify on the metal

```bash
uos vm create rebuild ~/os-forge/build/rebuild.iso --disk-gb 8
uos vm boot rebuild --wait 60
uos vm shot rebuild                       # the first boot — screenshot it, it's a moment
uos test app rebuild --app ~/apps/notepad.exe --workspace ~/os-forge --label notepad
uos test app rebuild --app ~/apps/cmd.exe     --workspace ~/os-forge --label cmd
uos test report ~/os-forge
uos test regress ~/os-forge regressed "notepad: file open dialog asserts in comdlg32 stub"
uos re diff ~/os-forge/api/xp-core-surface.json ~/os-forge/api/rebuild-core-surface.json \
    --workspace ~/os-forge
```

- First run almost certainly fails. That's the loop: failing app → `vm_screenshot` + captured
  stderr → which export is stubbed → spec → implement → re-test. One component at a time.
- Compatibility work is a ladder: exe loads → exe runs → dialog opens → file I/O works →
  app is useful. `compat_report` tracks per-app pass; `behavior_diff` tracks the interface
  ladder underneath it.

## Phase 8 — Iterate

Pass → next missing export / next app. Fail → restore snapshot, fix, re-test the *previously
passing* apps too (regressions first, features second). Journal every cycle.

## Phase 9 — Field note

```bash
uos kb new --os windows-xp --component kernel32 --title "notepad+cmd on the lite build" \
           --agent "your-name" --status working
# fill every section: route, behavior learned, verification, gotchas (symptom -> cause -> fix)
uos kb check knowledge/os/windows-xp/....md     # must pass before any PR
uos kb index
```

Update the phase checkboxes in `WORKSPACE.md`. With the user's OK, open the PR.

## What this looks like after a week of sessions

- `tests/RESULTS.md`: 40 app-runs, 12 pass, regressions logged per commit.
- `reports/behavior-diff-*.json`: kernel32 coverage 62% → 78%.
- `knowledge/os/windows-xp/`: four field notes, the next agent starts at 78%.
- The user's inventory app still crashes in `ole32` — and its spec is already half written.
