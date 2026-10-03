# universal-os

**Skills, tools, an MCP server and a shared knowledge base that let an AI coding agent reverse engineer an existing operating system from its ISO and rebuild it — ReactOS style — component by component, until apps written for the original OS run on the rebuild.**

Works with Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode, or anything that
reads `AGENTS.md` or speaks MCP. Point the agent at a Windows ISO (any version: XP, 7, 10, 11,
Server), it fingerprints the image, boots it in a headless QEMU sandbox, surveys what the OS
actually exposes, writes behavioral specs, scaffolds ReactOS-style C components, builds them,
boots the rebuild, and tests real Windows apps on it. Every session leaves field notes the next
agent starts from.

```
   ISO ──► fingerprint ──► sandbox VM ──► survey (API surface, traces)
                                            │
            behavioral specs ◄──────────────┘
                   │
            scaffold + build (ReactOS-style C, .spec exports)
                   │
            rebuilt image ──► boot in VM ──► test real apps ──► behavior_diff
                                                                    │
                                                        field note for the next agent
```

## Install

Pick your agent. Each gets the same skills, the universal-os MCP server, and the `uos` CLI.

| Agent | Install |
|---|---|
| **Claude Code** | `claude mcp add universal-os -- uv tool run universal-os-mcp` or clone and use `.mcp.json` |
| **Codex / Cursor / VS Code** | Clone the repo and start the agent inside it; configs in `.codex/config.toml`, `.cursor/mcp.json`, `.vscode/mcp.json` |
| **Skills only** (any agent) | `npx skills add <this-repo-url>` |
| **Anything else** | `git clone <this-repo>` and start your agent inside it |

**The CLI, anywhere:**
```bash
uv tool install <this-repo-url>        # or: pip install <this-repo-url>
```

You need Python 3.10+, and QEMU for the VM parts (git, cmake, ninja and a MinGW toolchain when
you reach the build phase):

```bash
sudo apt-get install -y qemu-system-x86 qemu-utils   # Debian/Ubuntu
brew install qemu                                    # macOS
winget install SoftwareFreedomConservancy.QEMU       # Windows
```

`uos env` checks all of it and prints what's missing.

## Try it

> Rebuild the core of the Windows XP SP3 ISO at `~/isos/en_win_xp_sp3.iso` far enough to run
> `notepad.exe` and `cmd.exe`.

> This is a Windows 7 ISO. Fingerprint it, boot it in a VM, dump the kernel32/user32/ntdll API
> surfaces, and tell me how far the ReactOS component set already covers it.

> Take my rebuilt workspace, test Notepad2 on it, and add compat quirks for everything that breaks.

The agent starts with the **build-any-os** skill and runs the same loop every time:
1. search the knowledge base; 2. fingerprint the ISO; 3. check the environment;
4. set up a sandbox lab (VM, snapshots); 5. survey the reference OS (API surfaces, traces);
6. pick the component route; 7. write behavioral specs; 8. build one working slice;
9. boot the rebuild and test real apps; 10. write a field note for the next agent.

## A knowledge base AIs write for AIs

`knowledge/` holds **field notes**: how specific OS rebuilds actually went — the exact ISO
versions, the component order that worked, the interface facts, the verification, the gotchas
(symptom → cause → fix). Every agent that finishes a milestone can open a PR with its note, so
the next agent starts where the last one left off.

```bash
uos kb search "windows xp ntdll"     # before you start: prior art
uos kb new --os "windows-xp" --component ntoskrnl --title "First boot" --agent "Claude"
uos kb check knowledge/os/windows-xp/....md
```

Contribution rules, for humans and AIs, are in `RULES.md`: no Microsoft binaries, no decompiled
code, no media links, honest status and verification.

## What's inside

| Part | What it does |
|---|---|
| **MCP server** (`uos-mcp`) | 32 tools over stdio: ISO inspect/fingerprint, VM lifecycle (boot, screenshot, snapshot, exec, file transfer), PE analysis, API-surface dumps, syscall-trace plans, behavior diffs, component scaffolds, compat shims, reference-repo cloning, app-compat testing, knowledge base |
| **`uos` CLI** | The same tools from a shell — for agents without MCP and for humans |
| **skills/build-any-os** | The whole loop, hard rules, and playbooks per phase (fingerprint, boot, survey, route, spec, build, verify, publish) |
| **knowledge/** | Field notes from previous rebuilds + a generated INDEX |
| **prompts/** | Ready-made phase prompts for any MCP client |
| **examples/** | A worked example: workspace layout, first build, first app test |
| **CI** | GitHub Action running the tests, CLI smoke checks and knowledge-base lint on every push |

## Rules it follows (moderate level — full text in `RULES.md`)

- **Everything untrusted runs inside the sandbox VM, never on the host.** The reference ISO is
  never mounted on the host; it is read with the built-in ISO parser or booted in QEMU.
- **Inspection is free; shipping is not.** Inside the VM the agent may run, trace, dump and
  analyze anything. What may *enter the rebuilt OS repo* is: interface facts (names, ordinals,
  versions, structures), behavioral specs, and clean-room code. What may not: Microsoft
  binaries, drivers, fonts, registry hives, decompiled output, links to OS media.
- **VM networking is OFF by default**; enabling it needs the user's explicit OK.
- **Snapshot before risky operations**; restore to undo.
- **Keep a journal:** `WORKSPACE.md` in the workspace. It becomes the field note at the end.
- **No activation/DRM/licensing bypass, no pirate media, ever.**

## License and stance

MIT. universal-os is tooling for interoperability and education — the same legal footing as
ReactOS and Wine. It ships no Microsoft code, no Microsoft binaries, and does not distribute
OS media. What you build with it must pass the same rules; `uos kb check` and CI enforce the
basics, and your jurisdiction and lawyer own the rest.
