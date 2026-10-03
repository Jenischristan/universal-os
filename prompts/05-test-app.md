# Phase 7 — Test an app on the rebuild

> Test `{{app}}` on the rebuilt build in VM `{{vm}}`: `test_app_in_vm` with workspace
> `{{workspace}}`, then `compat_report` and `regression_log` the outcome. For every failure:
> screenshot, find the stubbed/missing export that caused it, and propose either a component
> fix or a `gen_compat_layer` quirk. Re-test previously passing apps before claiming progress.
