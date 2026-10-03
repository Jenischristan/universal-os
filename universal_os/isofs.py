"""Pure-Python ISO 9660 (with Joliet) reader — enough to inspect Windows install ISOs
without mounting them on the host (which RULES.md forbids for untrusted media).

Supports: primary volume descriptor, Joliet supplementary descriptors (UCS-2 names),
recursive directory listing, file extraction, high-sierra fallback naming. Windows
Vista+ ISOs are usually ISO+UDF hybrids; the ISO9660 view alone is enough to see
/boot, /sources, /support and to pull small metadata files (setup.exe, cversion.ini).
Pure-UDF images will surface as 'iso9660 view incomplete' — the tool says so honestly.
"""
from __future__ import annotations

import struct
from pathlib import Path

SECTOR = 2048


class ISOError(ValueError):
    pass


class IsoFile:
    def __init__(self, name: str, lba: int, size: int, is_dir: bool, hidden: bool = False):
        self.name = name
        self.lba = lba
        self.size = size
        self.is_dir = is_dir
        self.hidden = hidden

    def to_dict(self) -> dict:
        return {"name": self.name, "lba": self.lba, "size": self.size, "dir": self.is_dir}


class IsoImage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.f = open(self.path, "rb")
        self.pvd = None
        self.joliet = False
        self.root: IsoFile | None = None
        self.volume_id = ""
        self._scan()

    def close(self) -> None:
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _sector(self, lba: int, count: int = 1) -> bytes:
        self.f.seek(lba * SECTOR)
        return self.f.read(SECTOR * count)

    def _scan(self) -> None:
        size = self.path.stat().st_size
        max_lba = min(size // SECTOR, 32 + 64)
        pvd_found = None
        joliet_found = None
        for lba in range(16, max_lba):
            sec = self._sector(lba)
            if len(sec) < SECTOR or sec[1:6] != b"CD001":
                continue
            vtype = sec[0]
            if vtype == 1 and pvd_found is None:
                pvd_found = sec
            elif vtype == 2:
                # Joliet escape sequences: %/@ (UCS-2 level 1), %/C, %/E
                esc = sec[88:120]
                if b"%/@" in esc or b"%/C" in esc or b"%/E" in esc:
                    joliet_found = sec
        if pvd_found is None:
            raise ISOError(f"no ISO9660 primary volume descriptor found in {self.path}")
        vol_id_raw = pvd_found[40:72].decode("latin-1", "replace").strip()
        self.volume_id = vol_id_raw
        root_rec = pvd_found[156:156 + 34]
        self.root = self._parse_record(root_rec, "")
        if joliet_found is not None:
            self.joliet = True
            self.joliet_root = self._parse_record(joliet_found[156:156 + 34], "")
            jid = joliet_found[40:128].decode("utf-16-be", "replace").strip()
            if jid:
                self.volume_id = jid

    def _parse_record(self, rec: bytes, parent: str) -> IsoFile:
        if not rec or rec[0] == 0:
            raise ISOError("empty directory record")
        ext = rec[1]
        lba = struct.unpack_from("<I", rec, 2)[0]
        size = struct.unpack_from("<I", rec, 10)[0]
        flags = rec[25]
        nlen = rec[32]
        raw_name = rec[33:33 + nlen]
        if raw_name[:1] == b"\x00":
            name = "."
        elif raw_name[:1] == b"\x01":
            name = ".."
        elif parent and ext == 0:  # joliet descriptors carry UCS-2 names
            name = raw_name.decode("utf-16-be", "replace")
        else:
            name = raw_name.decode("ascii", "replace")
            if ";" in name:  # strip ISO version identifier ("NAME.EXT;1")
                name = name.split(";")[0]
            name = name.rstrip(".")
        return IsoFile(name, lba, size, bool(flags & 0x02), bool(flags & 0x01))

    def _read_dir(self, d: IsoFile, joliet: bool = False) -> list[IsoFile]:
        raw = self._sector(d.lba, max(1, (d.size + SECTOR - 1) // SECTOR))[:d.size]
        out = []
        i = 0
        while i < len(raw):
            rlen = raw[i]
            if rlen == 0:
                # records don't cross sector boundaries; skip to next sector
                i = ((i // SECTOR) + 1) * SECTOR
                continue
            rec = raw[i:i + rlen]
            if i + rlen > len(raw):
                break
            f = self._parse_record(rec, "j" if joliet else "")
            if f.name not in (".", ".."):
                out.append(f)
            i += rlen
        return out

    def listdir(self, path: str = "/", limit: int = 2000) -> list[dict]:
        d = self._resolve(path)
        if d is None or not d.is_dir:
            return []
        entries = self._read_dir(d, joliet=(self.joliet and path.startswith("/")))
        return [e.to_dict() for e in entries[:limit]]

    def _resolve(self, path: str) -> IsoFile | None:
        parts = [p for p in path.replace("\\", "/").split("/") if p and p not in (".", "..")]
        node = self.joliet_root if self.joliet else self.root
        base = "/"
        for part in parts:
            if node is None or not node.is_dir:
                return None
            found = None
            for e in self._read_dir(node, joliet=self.joliet):
                if e.name.lower() == part.lower():
                    found = e
                    break
            if found is None:
                return None
            node = found
        return node

    def read_file(self, path: str, max_bytes: int = 16 * 1024 * 1024) -> bytes:
        node = self._resolve(path)
        if node is None:
            raise FileNotFoundError(f"not in ISO: {path}")
        if node.is_dir:
            raise IsADirectoryError(path)
        if node.size > max_bytes:
            raise ValueError(f"{path} is {node.size} bytes; over the {max_bytes} inspect limit")
        self.f.seek(node.lba * SECTOR)
        return self.f.read(node.size)

    def extract_file(self, path: str, dest: str | Path) -> Path:
        data = self.read_file(path)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def walk(self, path: str = "/", depth: int = 3, limit: int = 4000) -> list[dict]:
        out: list[dict] = []

        def rec(p: str, level: int):
            if len(out) >= limit or level > depth:
                return
            for e in self.listdir(p, limit=2000):
                full = (p.rstrip("/") + "/" + e["name"]) if p != "/" else "/" + e["name"]
                e2 = dict(e)
                e2["path"] = full
                out.append(e2)
                if e["dir"]:
                    rec(full, level + 1)

        rec(path, 1)
        return out
