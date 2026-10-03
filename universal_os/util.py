"""Small shared helpers."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def run(cmd: list[str], timeout: int = 120, cwd: str | None = None) -> tuple[int, str, str]:
    """Run a command; return (rc, stdout, stderr). Never raises for non-zero rc."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
            errors="replace",
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"executable not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s: {' '.join(cmd)}"
    except Exception as e:  # pragma: no cover
        return 1, "", f"{type(e).__name__}: {e}"


def which(binary: str) -> str | None:
    """Locate an executable portably. shutil.which covers PATH on every OS;
    the bash-login-shell fallback catches PATH entries added by profile scripts
    (common for QEMU on macOS/homebrew and MinGW installs)."""
    found = shutil.which(binary)
    if found:
        return found
    if os.name == "nt":
        return None  # no bash fallback on Windows
    rc, out, _ = run(["bash", "-lc", f"command -v {binary}"])
    out = out.strip()
    return out if (rc == 0 and out) else None


def jdump(obj, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def jload(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def append_md(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n")
    return path


_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


def split_front_matter(text: str) -> tuple[dict, str]:
    """Parse a simple 'key: value' YAML front matter block (no nesting needed)."""
    m = _FRONT_MATTER.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, text[m.end():]


def human_size(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


def split_guest_args(s: str) -> list[str]:
    """Split a guest command line on whitespace, honoring ' and " quoting, and
    keeping backslashes literal (Windows cmd semantics — NOT POSIX escapes).

    shlex.split(posix=True) eats backslashes ('C:\\uos' -> 'C:uos'); posix=False
    keeps them but also keeps quote characters in tokens and refuses to group.
    Guest command lines are Windows-style most of the time, so quotes group and
    backslashes stay put:
        split_guest_args('/c mkdir "C:\\uos-tests" 2>nul')
          -> ['/c', 'mkdir', 'C:\\uos-tests', '2>nul']
    """
    tokens: list[str] = []
    cur: list[str] = []
    quote: str | None = None
    for ch in s:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur.append(ch)
        elif ch in ("'", '"'):
            quote = ch
        elif ch.isspace():
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        tokens.append("".join(cur))
    return tokens
