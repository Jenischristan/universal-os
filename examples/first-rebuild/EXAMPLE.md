# Worked example — first-rebuild workspace

What a healthy first-session workspace looks like after Phases 0-7 of the loop. The tooling
makes this shape; keep it.

```
os-forge/
├── WORKSPACE.md                 # the journal — the most important file in the repo
├── workspace.json               # config + artifact registry (auto-updated by tools)
├── iso/                         # (empty here: reference ISO stays wherever the user keeps it)
├── vm/                          # VM notes for this workspace (qcow2 disks live in UOS_HOME)
├── api/
│   ├── xp-core-surface.json     # dump_api_surface output: the target contract
│   ├── xp-core-surface.md
│   └── rebuild-core-surface.json
├── spec/
│   ├── ntdll.md                 # behavioral specs: one entry per export, spec-before-code
│   ├── kernel32.md
│   └── trace-plan-20261003-*.json
├── src/
│   ├── include/                 # shared headers (interface facts as C declarations)
│   ├── boot/  drivers/  subsystems/
│   ├── dll/
│   │   ├── kernel32_lite/       # scaffold_component output, partially implemented
│   │   │   ├── CMakeLists.txt  kernel32_lite.spec  kernel32_lite.c  README.md
│   │   └── compat_user32/       # gen_compat_layer output: per-quirk shims
│   ├── shell/  apps/
│   └── build/                   # build outputs — never committed
├── tests/
│   ├── test_main.c              # per-component API tests (ReactOS-style CHECK macro)
│   ├── results/                 # test_app_in_vm JSONs (exit codes, screenshots)
│   ├── RESULTS.md               # | date | app | vm | PASS/FAIL | exit | result file |
│   └── REGRESSIONS.md           # | date | status | note |
├── third-party/
│   └── reactos/                 # clone_reference_repo — reference only, license intact
├── reports/
│   ├── compat-20261003-*.json   # compat_report output
│   └── behavior-diff-*.json     # the coverage ladder over time
└── tools/                       # session-specific helper scripts
```

## The three files that tell the story

1. **WORKSPACE.md** — every decision, version, fact and failure. If an agent dies mid-session,
   the next one rebuilds context from this file alone.
2. **reports/behavior-diff-*.json** — coverage going 41% → 62% → 78% is the whole project in
   one number.
3. **tests/RESULTS.md** — notepad.exe FAIL (missing comdlg32) → PASS, cmd.exe PASS. The goal,
   met.

## First session checklist

- [ ] `init_workspace` + journal started
- [ ] fingerprint journaled (version, build, layout, confidence)
- [ ] VM booted, `clean-install` snapshot taken
- [ ] core API surface dumped (api/), trace plan written (spec/)
- [ ] reactos cloned, route decided and journaled
- [ ] first component compiles
- [ ] first app test recorded (PASS or FAIL — both are progress)
- [ ] field note drafted and checked
