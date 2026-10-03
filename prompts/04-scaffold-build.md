# Phase 4/5/6 — Route, spec, build

> In `{{workspace}}`: diff the reference surface against the rebuild surface with
> `behavior_diff` (or the ReactOS tree if cloned), pick the top-3 modules to close the gap,
> `clone_reference_repo` what we need, `gen_api_stub`/`scaffold_component` them, write
> behavioral specs in spec/ for every export the goal app needs, then `build_plan` and compile
> what the host toolchain allows. Implement from specs only — decompiled output never enters
> the repo (RULES.md §4).
