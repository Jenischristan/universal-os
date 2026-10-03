# Phase playbooks — quick cards

One card per phase of the loop. Full prose: `SKILL.md` and `WORKFLOW.md`.

## Card: fingerprint (before any VM)
- `env_check` → `kb_search "<os>"` → `fingerprint_windows <iso>` → `iso_inspect <iso>`.
- Output to journal: version, build, layout, confidence, chosen API strategy (NT 5.x vs 6.x).
- Failure mode: UDF-only ISO (Joliet absent) → surface the honest error, don't guess version.

## Card: lab
- `vm_create` (network OFF) → `vm_boot --wait 60` → screenshot loop through setup.
- Snapshot `clean-install` right after first desktop. Snapshot again before every risky step.
- Under TCG: warn install time (30-90 min), prefer restores to reinstalls, keep VM count low.

## Card: survey
- Guest agent first (virtio-win ISO via `vm_mount_iso`, install, swap reference back).
- Extract core DLLs to ~/inspect/<os>/ (OUTSIDE repo) → `vm_get_file` → `dump_api_surface`
  → workspace api/. `trace_syscalls` plan per goal app; run in-guest; pull .etl back.
- Journal headline numbers: modules, export counts, per-app import hotspots.

## Card: route
- `clone_reference_repo reactos` (+wine for user-mode) → dump ReactOS's own surface once →
  `behavior_diff` → work queue sorted by coverage %, filtered to what the goal app imports.
- Decide per module: reuse / extend / stand-alone / shim. Journal the route before building.

## Card: spec-before-code
- One entry per export: signature (surface), documented behavior, error paths, verify method.
- Docs first, traces second, decompilation last (moderate rules; RULES.md §4). No spec → no code.

## Card: build
- `scaffold_component` / `gen_api_stub` → implement minimum for the goal app →
  `build_plan` → cmake+ninja (MinGW). ReactOS idioms: .spec tables, W-over-Nt, small DLLs.

## Card: verify
- Own VM for the rebuild image. `test_app_in_vm` per app → RESULTS.md → `compat_report` →
  `regression_log` on breaks → `behavior_diff` for the interface ladder. One component per cycle.

## Card: field note
- `kb_new` → fill every section → `kb_check` (must pass) → `kb_index` → PR with user OK.
- Gotchas as symptom → cause → fix. Honest status; exact versions; no media links, no dumps.
