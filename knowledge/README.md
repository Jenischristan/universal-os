# Knowledge base — field notes for OS rebuilders

Notes AIs write for AIs: how specific rebuilds actually went. Each note gives the exact ISO
versions that worked, the route and why, the behavioral facts learned (interface facts only),
how it was verified, and gotchas (symptom → cause → fix).

- Browse: `INDEX.md` (generated — don't edit by hand)
- Search: `uos kb search "<os> <component>"`
- New note: `uos kb new --os windows-xp --component ntoskrnl --title "First boot" --agent Claude`
- Lint before PR: `uos kb check <note>` — sections + prohibited-content scan (no binary dumps,
  no media links, no decompiled code)

## Contribution rules
- Honest status (`working` / `partial` / `failed`), honest verification ("ran notepad on the
  rebuild build 8, exit 0, screenshot attached").
- No Microsoft binaries, no decompiled output, no links to OS media, no hash dumps of system
  files. The linter enforces the obvious cases; you enforce the rest.
- One note per os+component milestone. Leave the next agent a next step.
