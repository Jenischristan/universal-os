# universal-os

An OS-reconstruction toolkit and a shared knowledge base for AI coding agents: Claude Code,
Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode and anything else that reads `AGENTS.md`.
When someone opens an agent in this repo, they almost always want to **reverse engineer an
operating system from an ISO and rebuild it ReactOS-style so its apps run on the rebuild**, or
to learn how a previous rebuild went.

## Start here
1. **Read `SKILL.md` and follow its loop:** intake → fingerprint → lab → survey → route →
   spec → build → verify → iterate → field note.
2. **Search the knowledge base first:** `uos kb search "<os> <component>"`. Other agents may
   already have written down the exact ISO versions, routes and gotchas (`knowledge/INDEX.md`).
3. **At the end, share what you learned:** write a field note (`uos kb new ...`), lint it
   (`uos kb check <note>`) and, once your human agrees, open a PR. See `knowledge/README.md`.

## Tools
- **`uos-mcp`** is the MCP server (stdio). MCP clients get all 39 tools with descriptions that
  carry the guardrails inline. Configs: `.mcp.json` (Claude Code), `.codex/config.toml` (Codex),
  `.cursor/mcp.json` (Cursor), `.vscode/mcp.json` (VS Code / Copilot).
- **`bin/uos`** is the CLI — same tools from a shell. It sets itself up with `uv`. Every group
  has `--help`:
  - `iso`: inspect install media without mounting it, fingerprint the Windows version
  - `vm`: create/boot/screenshot/snapshot/exec/file-transfer/shutdown for the sandbox VM
  - `re`: PE analysis, API-surface dumps, trace plans, behavior diffs
  - `forge`: workspaces, component scaffolds, API stubs, compat shims, reference clones, build plans
  - `test`: app-compat runs in the VM, compatibility reports, regression log
  - `kb`: the knowledge base
  - `env`: check host toolchain (QEMU, git, cmake, ninja, MinGW, KVM)
- **Skills** (`skills/*/SKILL.md`, Agent Skills format) are linked where each agent looks for
  them: `.agents/skills` (Codex and others), `.claude/skills`, `.gemini/skills`, `.github/skills`.
- **Phase playbooks:** `skills/build-any-os/references/`.
- **Worked example:** `examples/first-rebuild/EXAMPLE.md`.
- **Prompts:** `prompts/` — one ready-made prompt per phase for any MCP client.

## Rules (full reasoning in `RULES.md`)
- **Sandbox only:** untrusted media and unknown binaries run inside the VM, never on the host.
  Never mount the reference ISO on the host.
- **What you may keep:** interface facts (function names, ordinals, parameter counts, version
  numbers, structures), behavioral specs, and clean-room code you wrote from those specs.
- **What you may never keep or ship:** Microsoft binaries, drivers, fonts, registry hives,
  decompiled output, ISO/media links. Decompiled work stays outside the repo (e.g.
  `~/inspect/`) and never enters `src/`, `spec/`, tests, notes or reports.
- **Networking:** VM network is OFF by default. Ask the user before enabling it. Never upload
  ISOs, dumps or traces anywhere.
- **No bypass:** never work on activation, DRM, licensing or ownership checks, and never help
  pirate media. This toolkit exists for interoperability, the way ReactOS and Wine do.
- **Snapshots:** `vm snapshot` before risky VM operations; restore to undo.
- **Processes:** kill inside guests by exact PID, never by name pattern.
- **Ask first** before: enabling VM networking, publishing anything (PRs included), deleting
  snapshots or workspaces, disks larger than 60 GB.
- **Keep a journal:** `WORKSPACE.md` in the workspace — paths, versions, interface facts, what
  failed and why, the next step. Anything not in the journal is lost at the next context
  compaction.

## Working on the toolkit itself
- **Python:** 3.10+, deps `mcp` and `pyyaml`. Code lives in `universal_os/`, one module per
  tool group (`vmtools` logic in `qemu.py`, `retools.py`, `forgetools.py`, `testtools.py`,
  `knowledge.py`), with `cli.py` and `mcp_server.py` as the two front doors.
- **No heavyweight dependencies:** the PE parser, ISO9660 reader and PNG encoder are pure
  Python on purpose — the tool must run on a locked-down host with nothing but QEMU installed.
- **Tests:** `uv run --with pytest pytest -q tests`. CI also runs every CLI group's `--help`,
  an MCP stdio handshake, and `uos kb check` over the knowledge base.
- **Wording:** keep skills and docs agent-neutral ("the agent", not a product name) except in
  sections about one specific agent.
