# RULES.md — what the agent does and does not do

Guardrail level: **moderate** (chosen by the user). Moderate means: inspection inside the
sandbox is free; nothing copyrighted may enter the rebuilt OS repo or leave the user's machine.
The reasoning behind every rule is here, so the agent can apply it to cases these lists miss.

The one-line version: **look at anything inside the sandbox; ship only clean-room code,
interface facts and behavioral specs; when in doubt, ask the human.**

---

## 1. The sandbox boundary (hard rule)

- All analysis of untrusted media — the reference ISO, its files, binaries extracted from it,
  apps under test — happens **inside the QEMU VM** or through the toolkit's pure-Python
  readers (`iso_inspect`, `analyze_pe`), which never execute what they read.
- **Never mount the reference ISO on the host.** Never execute reference binaries on the host.
  Never open host ports to the VM.
- The host's role is: orchestrate QEMU, store the workspace, run compilers. Nothing else
  touches untrusted content.
- Why: OS media is effectively a full-system attack surface. One auto-run handler in an
  installer is enough. The VM gives blast radius; the pure-Python readers give eyes without
  execution.

## 2. What may enter the rebuilt OS repo (the "keep" list)

- **Interface facts:** function names, ordinals, parameter counts, calling conventions,
  structure layouts, version numbers, registry key names, error codes. These are facts, the
  same facts ReactOS and Wine publish, and they are the rebuild's contract.
- **Behavioral specs:** documented and observed behavior ("`CloseHandle(NULL)` returns FALSE
  with `ERROR_INVALID_HANDLE`"), written from public docs plus traces you ran.
- **Clean-room code:** C you wrote from those specs, ReactOS-style.
- **Your own build files, tests, reports, notes.**

## 3. What may never enter the rebuilt OS repo (the "forbidden" list)

- **Microsoft binaries** in any form: DLLs, EXEs, drivers, fonts, cursors, sounds, themes,
  registry hives — even "just one, for testing". Copying a file out of the VM for host-side
  *inspection* is fine at this level; committing it anywhere in the workspace is not.
- **Decompiled or disassembled output** — in the repo, in `spec/`, in tests, in notes, in
  commit messages. Decompiled material may inform your understanding (see §4) but only the
  behavioral summary may be written down here.
- **Links to OS media** (ISO/WIM/ESD) or instructions for obtaining it unofficially. Reference
  the *version* (`XP SP3, build 2600`), never a source.
- **Hash dumps / raw blobs** of reference files (a name or version is a fact; a hash table of
  system files is a red-flag artifact). The kb linter flags these.
- **Activation, DRM, licensing, ownership-check** work in any form — no cracks, no key
  generators, no bypass research, no "just to see". Refuse and explain.
- **Pirated media or apps** in the VM. If the user supplies one, stop and say why.

## 4. Decompilation policy (the moderate compromise)

At this guardrail level the agent **may** decompile reference code inside the sandbox to
understand behavior — the same way a developer reads assembly when a doc is missing — subject
to:

1. Decompiled material stays in the **inspect dir** (outside the workspace, e.g.
   `~/inspect/<os>/`), never committed, never in PRs.
2. What crosses into the repo is the **behavioral spec**: an English/C-level description of
   what the code does, written by the agent, in the agent's own words and structure.
3. If a behavior is describable from public documentation, use the documentation instead.
   Decompilation is the fallback, not the default.
4. **Never** reproduce code structure that is recognizable from the original (function body
   shapes, unique comments, obvious literal chains). If your spec reads like the decompiler
   output with names changed, rewrite it.

The strict clean-room alternative (no decompilation at all, one team specs and another
implements) is available: set the workspace guardrail to `strict` and follow §5.

## 5. If the user asks for strict clean-room

Two-agent protocol: the spec agent observes and writes behavioral specs only; the implement
agent sees specs, never reference material, and may not ask what "the real one" does. Heavier,
slower, legally strongest — this is the ReactOS/Wine posture. All tools support it; only the
working habits change.

## 6. Network and data flow

- VM networking is **off** by default (`vm_create network=false`). Enabling it needs the
  user's explicit OK, per VM, for a stated reason (Windows Update? activation is NOT an
  acceptable reason; app-level network testing is).
- Never upload ISOs, dumps, traces, screenshots or workspace content anywhere. The user's
  media and your findings stay on the user's machine.
- `clone_reference_repo` fetches public open-source repositories — that is the one allowed
  outbound transfer. Anything else: ask.

## 7. VM hygiene

- One VM per purpose: `ref-os` (the reference install), `rebuild` (the rebuilt image), plus
  throwaways for sketchy experiments. Name them that way.
- `vm_snapshot` before: app installs, component swaps, registry experiments, anything with
  "let's see what happens". Restore is cheap; reinstalling XP under TCG is not.
- Shut down cleanly (`vm_shutdown`); force-kill only wedged VMs, then journal why it wedged.
- Keep guest-side experiments inside `C:\uos-tests\` so snapshots restore cleanly.
- In-guest kills by exact PID, never by name pattern (classic Windows services share names).

## 8. Honesty rules

- Report what actually ran: exit codes, screenshots, coverage numbers. A passing test you
  didn't run is a lie with extra steps.
- `compat_report` and `regression_log` exist so progress claims are auditable — use them, and
  log regressions even when embarrassing (especially when embarrassing).
- Field notes: honest status (`working` / `partial` / `failed`), exact ISO versions, real
  gotchas. The next agent bets their session on your note.
- If the rebuild is far from the goal ("we can boot, notepad is 6 months out"), say so. OS
  rebuilds are years-long projects; the honest unit of progress is "this app now launches".

## 9. Ask-first list

- Enabling VM networking.
- Publishing anything: pushing the workspace, opening PRs, sharing notes.
- Deleting snapshots, VMs, or workspaces.
- Disks > 60 GB or RAM > 8 GB per VM.
- Installing anything in the guest beyond the goal app and the QEMU guest agent.
- Any time you cannot decide whether something belongs in the repo.

## 10. Journal rule

`WORKSPACE.md` is the source of truth: what was tried, what failed, what is next, the
interface facts discovered, the decisions taken. Update it as you go — not at the end. At the
next context compaction, everything not in the journal is gone.
