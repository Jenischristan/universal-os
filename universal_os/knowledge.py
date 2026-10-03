"""Knowledge base — field notes AIs write for AIs about OS rebuilding.

Mirrors the universal-modder pattern: front-matter'd markdown notes under knowledge/,
a generated INDEX.md, and check/lint so a note never ships prohibited content.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .util import split_front_matter

FORBIDDEN_IN_NOTE = [
    # (regex, reason)
    (r"(?i)sha1[:\s]*[0-9a-f]{40}", "raw hash dumps of MS files — reference by name instead"),
    (r"(?i)base64\s*[:=]?\s*[A-Za-z0-9+/=]{200,}", "possible embedded binary blob"),
    (r"(?i)\b(registry hive|ntuser\.dat|system32\\[^\s]+\.dll)\b\s*[:=]\s*\S+\.(dll|exe|hiv)",
     "looks like a path to a redistributable MS binary"),
    (r"(?i)https?://\S*\.(iso|wim|esd|gho)\b", "link to copyrighted OS media"),
]

NOTE_TEMPLATE = """\
---
title: "{title}"
os: "{os}"
component: "{component}"
status: "{status}"
agent: "{agent}"
date: "{date}"
tags: [{tags}]
---

# {title}

## What was being built
<!-- which OS/component, which reference ISO and version -->

## The route that worked
<!-- fingerprint -> boot -> survey -> which components first; exact commands -->

## What the reference actually does
<!-- behavioral facts learned from the VM: interface facts only, no dumps -->

## How it was verified
<!-- which tools, which tests, which screenshots -->

## Gotchas
<!-- symptom -> cause -> fix, one per bullet -->

## Next step
<!-- leave the workspace in a state the next agent can continue from -->
"""


def kb_path(kb_dir: str | None = None) -> dict:
    """Resolve (and report) which knowledge-base roots are in effect.

    Roots, in priority order: an explicit kb_dir; a repo checkout (knowledge/
    next to the package); the copy packaged inside the wheel
    (universal_os/_data/knowledge, read-only seed notes); UOS_HOME/knowledge
    (the user's own notes, created on demand). Search covers every root that
    exists; new notes always land in the writable root. The report exists so
    agents and humans can see *why* a search came back empty."""
    if kb_dir:
        p = Path(kb_dir).expanduser().resolve()
        return {"root": str(p), "source": "explicit", "writable": True, "roots": [str(p)]}
    pkg_dir = Path(__file__).resolve().parent
    roots: list[str] = []
    repo_kb = pkg_dir.parent / "knowledge"
    if (repo_kb / "INDEX.md").exists():
        return {"root": str(repo_kb), "source": "repo", "writable": True,
                "roots": [str(repo_kb)]}
    packaged_kb = pkg_dir / "_data" / "knowledge"
    if (packaged_kb / "INDEX.md").exists():
        roots.append(str(packaged_kb))
    import os
    home = os.environ.get("UOS_HOME", "~/.universal-os")
    user_kb = Path(home).expanduser() / "knowledge"
    user_kb.mkdir(parents=True, exist_ok=True)
    roots.append(str(user_kb))
    return {"root": str(user_kb), "source": "package+UOS_HOME" if len(roots) > 1
            else "UOS_HOME", "writable": True, "roots": roots}


def _notes_root(kb_dir: str | None = None) -> Path:
    """The writable root: where new notes go and where INDEX.md is generated."""
    return Path(kb_path(kb_dir)["root"])


def _search_roots(kb_dir: str | None = None) -> list[Path]:
    """Every root to search: the writable one plus any read-only packaged seed."""
    info = kb_path(kb_dir)
    return [Path(r) for r in info.get("roots", [info["root"]])]


# Template files that are not field notes themselves (exact names, so a legit note
# with 'note' in its filename is still indexed).
_NON_NOTE_FILES = {"INDEX.md", "README.md", "NOTE-TEMPLATE.md", "TEMPLATE.md"}


def _iter_notes(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md") if p.name.upper() not in _NON_NOTE_FILES)


def search(query: str, kb_dir: str | None = None, limit: int = 20) -> list[dict]:
    terms = [t for t in re.split(r"\s+", query.strip().lower()) if t]
    hits = []
    seen: set[str] = set()
    for root in _search_roots(kb_dir):
        for p in root.rglob("*.md"):
            if p.name.upper() in _NON_NOTE_FILES or str(p) in seen:
                continue
            seen.add(str(p))
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            meta, body = split_front_matter(text)
            blob = (p.stem + " " + text).lower()
            score = sum(blob.count(t) for t in terms)
            if score:
                try:
                    rel = str(p.relative_to(root))
                except ValueError:
                    rel = p.name
                hits.append({
                    "note": rel,
                    "root": "user" if root == _notes_root(kb_dir) else "seed",
                    "score": score,
                    "title": meta.get("title", p.stem),
                    "os": meta.get("os", ""),
                    "component": meta.get("component", ""),
                    "status": meta.get("status", ""),
                    "date": meta.get("date", ""),
                })
    hits.sort(key=lambda h: -h["score"])
    return hits[:limit]


def new_note(os_name: str, component: str, title: str, agent: str = "ai-agent",
             status: str = "working", tags: str = "", kb_dir: str | None = None,
             out: str | None = None) -> dict:
    root = _notes_root(kb_dir)
    slug = re.sub(r"[^a-z0-9-]+", "-", f"{os_name}-{component}-{title}".lower()).strip("-")[:80]
    path = Path(out) if out else root / "os" / os_name.lower().replace(" ", "-") / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"note exists: {path}")
    path.write_text(NOTE_TEMPLATE.format(
        title=title, os=os_name, component=component, status=status, agent=agent,
        date=time.strftime("%Y-%m-%d"), tags=tags,
    ), encoding="utf-8")
    return {"note": str(path), "next": "fill every section; then run kb_check before opening a PR"}


def check_note(path: str) -> dict:
    """Lint one note: required sections + prohibited-content scan."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    meta, body = split_front_matter(text)
    problems: list[str] = []
    required = ["What was being built", "The route that worked",
                "How it was verified", "Gotchas"]
    for r in required:
        if f"## {r}" not in text:
            problems.append(f"missing section: {r}")
    if not meta:
        problems.append("missing front matter")
    unfilled = len(re.findall(r"<!--", body))
    if unfilled and str(meta.get("status", "working")).lower() == "working":
        problems.append(f"{unfilled} unfilled placeholder comment(s) — fill every section")
    for rx, reason in FORBIDDEN_IN_NOTE:
        m = re.search(rx, text)
        if m:
            problems.append(f"prohibited content ({reason}): matched near "
                            f"'{text[max(0, m.start() - 20):m.end() + 20]}...'")
    note_status = str(meta.get("status", "working")).lower()
    if "TODO" in body and note_status == "working":
        problems.append("status says working but the note still has TODO placeholders")
    return {"note": str(p), "ok": not problems, "problems": problems}


def index(kb_dir: str | None = None) -> dict:
    """Regenerate INDEX.md from note front matter (written to the writable root)."""
    root = _notes_root(kb_dir)
    rows = []
    for p in _iter_notes(root):
        try:
            meta, _ = split_front_matter(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append((meta, p))
    lines = ["# Knowledge base index",
             "",
             "_Generated by `uos kb index`; don't edit by hand._",
             "",
             "## Notes",
             "",
             "| OS | Component | Note | Status | Agent | Date |",
             "|---|---|---|---|---|---|"]
    for meta, p in sorted(rows, key=lambda r: (r[0].get("os", ""), r[0].get("date", ""))):
        rel = p.relative_to(root)
        lines.append(f"| {meta.get('os', '?')} | {meta.get('component', '?')} "
                     f"| [{meta.get('title', p.stem)}]({rel}) | {meta.get('status', '?')} "
                     f"| {meta.get('agent', '?')} | {meta.get('date', '?')} |")
    (root / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"index": str(root / "INDEX.md"), "notes": len(rows)}
