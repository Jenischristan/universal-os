# Safety reasoning — why the rules are what they are

Full rule text: RULES.md. This card is the why, so the agent can apply rules to novel cases.

- **Sandbox boundary.** OS media is a full-system attack surface (installers auto-run handlers,
  boot code, drivers). The VM contains blast radius; the pure-Python ISO/PE readers give
  inspection without execution. Mounting untrusted media on the host defeats all of it.
- **Keep-list vs forbidden-list.** Copyright law (and the ReactOS/Wine precedent) draws the
  line exactly where we do: facts and interfaces are not protected expression; binaries and
  creative assets are. Decompiled bodies are protected expression rearranged — so understanding
  is allowed (moderate level), committing is not.
- **Networking off.** The reference OS in the VM can phone home, update, or activate; each
  breaks reproducibility or violates licensing. Default off, per-VM opt-in with a reason.
- **No DRM/activation work.** Bypass research is illegal in most jurisdictions regardless of
  intent, and irrelevant to interoperability: the rebuild never needs a license server.
- **Snapshots.** The cheapest undo in systems work. Risk without a snapshot is a session-wide
  gamble; with one, it is a one-line revert.
- **Honest reporting.** Every compat claim in this toolkit is backed by a recorded exit code
  and a screenshot. That is what makes the knowledge base trustworthy for the next agent.
