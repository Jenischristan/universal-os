# Phase 3 — Survey the reference OS

> In VM `{{vm}}`: install the QEMU guest agent (swap in the virtio-win ISO with
> `vm_mount_iso`, install, swap back), then survey:
> extract the core system DLLs OUTSIDE the repo (~/inspect/), pull them out with `vm_get_file`,
> run `dump_api_surface` into `{{workspace}}/api/`, write the in-guest trace plan with
> `trace_syscalls`, and journal the top findings + headline export counts in WORKSPACE.md.
> Nothing from the inspected copies enters the workspace — only the generated surface.
