"""Pure-Python PE (Portable Executable) analyzer — no external dependencies.

Reads what an AI needs when surveying a Windows binary it is allowed to *inspect*
(see RULES.md): headers, machine/subsystem, timestamps, sections, import table,
export table and the VS_VERSIONINFO resource strings (ProductVersion, FileVersion,
ProductName, OriginalFilename). Version resources are the cheapest reliable way to
fingerprint a Windows build or a third-party app.

This module only reports metadata and interface facts (names, ordinals, RVA sizes).
It never decompiles and never emits code.
"""
from __future__ import annotations

import struct
from pathlib import Path

MACHINES = {
    0x014C: "i386",
    0x8664: "x86_64",
    0x01C0: "arm",
    0xAA64: "arm64",
    0x01C4: "armnt",
}

SUBSYSTEMS = {
    1: "native", 2: "windows-gui", 3: "windows-cui", 5: "os2-cui",
    7: "posix-cui", 9: "windows-ce-gui", 10: "efi-application",
    11: "efi-boot-driver", 12: "efi-runtime-driver", 13: "efi-rom",
    14: "xbox", 16: "windows-boot-application",
}

DIRECTORY_NAMES = [
    "export", "import", "resource", "exception", "security", "basereloc",
    "debug", "architecture", "globalptr", "tls", "loadconfig", "boundimport",
    "iat", "delayimport", "comdescriptor", "reserved",
]

CHARACTERISTICS = {
    0x0001: "RELOCS_STRIPPED", 0x0002: "EXECUTABLE_IMAGE", 0x0004: "LINE_NUMS_STRIPPED",
    0x0008: "LOCAL_SYMS_STRIPPED", 0x0010: "AGGRESIVE_WS_TRIM", 0x0020: "LARGE_ADDRESS_AWARE",
    0x0040: "16BIT", 0x0080: "BYTES_REVERSED_LO", 0x0100: "32BIT_MACHINE",
    0x0200: "DEBUG_STRIPPED", 0x0400: "REMOVABLE_RUN_FROM_SWAP", 0x0800: "NET_RUN_FROM_SWAP",
    0x1000: "SYSTEM", 0x2000: "DLL", 0x4000: "UP_SYSTEM_ONLY", 0x8000: "BYTES_REVERSED_HI",
}


class PEError(ValueError):
    pass


def _read_cstr(buf: bytes, off: int) -> str:
    end = buf.find(b"\x00", off)
    if end < 0:
        end = len(buf)
    return buf[off:end].decode("latin-1", "replace")


def _read_utf16z(buf: bytes, off: int) -> str:
    out = []
    while off + 1 < len(buf):
        ch = struct.unpack_from("<H", buf, off)[0]
        if ch == 0:
            break
        out.append(chr(ch))
        off += 2
    return "".join(out)


def _parse_version_strings(resource_rva: int, size: int, data: bytes, sections) -> dict:
    """Extract VS_VERSIONINFO key/value pairs by walking the resource directory."""
    strings: dict[str, str] = {}
    blob = _rva_slice(resource_rva, size, data, sections)
    if not blob:
        return strings
    # Walk the resource tree: root -> TYPE 16 (VERSIONINFO) -> ID -> lang, then to leaf data.
    def walk(off: int, level: int, path: list[int]) -> None:
        if off + 16 > len(blob) or level > 3:
            return
        chars, timestamp, _major, _minor, named, ident = struct.unpack_from("<IIHHHH", blob, off)
        entry_off = off + 16
        for k in range(named + ident):
            if entry_off + 8 > len(blob):
                return
            name_id, offset = struct.unpack_from("<II", blob, entry_off + k * 8)
            high = offset & 0x80000000
            child = (offset & 0x7FFFFFFF) + off
            if high:
                walk(child, level + 1, path + [name_id])
            else:
                data_rva, _data_size2, _cp, _res = struct.unpack_from("<IIII", blob, child)
                leaf = _rva_slice(data_rva, 0x10000, data, sections)
                if leaf:
                    _scrape_version_strings(leaf, strings)
    walk(0, 0, [])
    return strings


def _scrape_version_strings(leaf: bytes, out: dict) -> None:
    """VS_VERSIONINFO is a variable key/value tree; pull the standard keys."""
    # Bounded scan: keys and values are UTF-16LE, zero-terminated.
    i = 0
    last_key = ""
    while i + 2 < len(leaf):
        s = _read_utf16z(leaf, i)
        if not s:
            i += 2
            continue
        step = 2 * (len(s) + 1)
        i += step
        if i % 4:
            i += 4 - (i % 4)
        low = s.lower()
        if low in (
            "stringfileinfo", "versioninfo", "varfileinfo", "stringtable",
            "productversion", "fileversion", "productname", "companyname",
            "filedescription", "originalfilename", "internalname", "legalcopyright",
            "comments", "privatebuild", "specialbuild",
        ):
            if low in ("productversion", "fileversion", "productname", "companyname",
                       "filedescription", "originalfilename", "internalname",
                       "legalcopyright", "comments"):
                if i + 2 <= len(leaf):
                    val = _read_utf16z(leaf, i)
                    if val:
                        out[low] = val
                last_key = low
        # value skip: after reading a value, re-align handled next loop


def _rva_to_off(rva: int, sections: list[dict]) -> int | None:
    for s in sections:
        if s["virtual_address"] <= rva < s["virtual_address"] + max(s["virtual_size"], s["raw_size"]):
            delta = rva - s["virtual_address"]
            if delta < s["raw_size"]:
                return s["raw_offset"] + delta
    return None


def _rva_slice(rva: int, size: int, data: bytes, sections) -> bytes:
    off = _rva_to_off(rva, sections)
    if off is None:
        return b""
    return data[off:off + size]


def parse_pe(path: str | Path, max_imports: int = 4096, max_exports: int = 8192) -> dict:
    data = Path(path).read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise PEError(f"not an MZ executable: {path}")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if e_lfanew + 6 > len(data) or data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        raise PEError(f"PE\\0\\0 signature not found: {path}")

    coff = e_lfanew + 4
    machine, nsec, _ts, _sym, _nsym, opt_size, chars = struct.unpack_from("<HHIIIHH", data, coff)
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0] if opt + 2 <= len(data) else 0
    pe32plus = magic == 0x20B
    if magic not in (0x10B, 0x20B):
        raise PEError(f"unknown optional-header magic 0x{magic:04x}: {path}")

    # Optional header fields common to both flavours.
    # PE32:  BaseOfData at 28, ImageBase@28? no: BaseOfCode@20, BaseOfData@24, ImageBase@28
    # PE32+: no BaseOfData, ImageBase is 8 bytes at 24
    if pe32plus:
        (linker_major, linker_minor, code_size, init_size, uninit_size, entry_rva,
         code_rva) = struct.unpack_from("<BBIIIII", data, opt)  # ...+BaseOfCode
        image_base = struct.unpack_from("<Q", data, opt + 24)[0]
        dd_off = opt + 112
        subsystem = struct.unpack_from("<H", data, opt + 68)[0]
        major_os = struct.unpack_from("<H", data, opt + 40)[0]
        minor_os = struct.unpack_from("<H", data, opt + 42)[0]
        major_sub = struct.unpack_from("<H", data, opt + 48)[0]
        minor_sub = struct.unpack_from("<H", data, opt + 50)[0]
    else:
        (linker_major, linker_minor, code_size, init_size, uninit_size, entry_rva,
         code_rva, data_rva) = struct.unpack_from("<BBIIIIII", data, opt)  # +BaseOfCode+BaseOfData
        image_base = struct.unpack_from("<I", data, opt + 28)[0]
        dd_off = opt + 96
        subsystem = struct.unpack_from("<H", data, opt + 68)[0]
        major_os = struct.unpack_from("<H", data, opt + 40)[0]
        minor_os = struct.unpack_from("<H", data, opt + 42)[0]
        major_sub = struct.unpack_from("<H", data, opt + 48)[0]
        minor_sub = struct.unpack_from("<H", data, opt + 50)[0]

    num_dirs = struct.unpack_from("<I", data, dd_off - 4)[0]
    dirs = []
    for i in range(min(num_dirs, 16)):
        rva, size = struct.unpack_from("<II", data, dd_off + i * 8)
        dirs.append({"name": DIRECTORY_NAMES[i], "rva": rva, "size": size})

    # Sections
    sec_off = opt + opt_size
    sections = []
    for i in range(nsec):
        o = sec_off + i * 40
        if o + 40 > len(data):
            break
        raw = data[o:o + 40]
        name = raw[:8].rstrip(b"\x00").decode("latin-1", "replace")
        vsize, vaddr, rsize, roff = struct.unpack_from("<IIII", raw, 8)
        sections.append({
            "name": name, "virtual_size": vsize, "virtual_address": vaddr,
            "raw_size": rsize, "raw_offset": roff,
        })

    out: dict = {
        "path": str(path),
        "file_size": len(data),
        "machine": MACHINES.get(machine, f"0x{machine:04x}"),
        "bits": 64 if pe32plus else 32,
        "subsystem": SUBSYSTEMS.get(subsystem, str(subsystem)),
        "linker_version": f"{linker_major}.{linker_minor}",
        "os_version": f"{major_os}.{minor_os}",
        "subsystem_version": f"{major_sub}.{minor_sub}",
        "image_base": hex(image_base),
        "entry_rva": hex(entry_rva),
        "characteristics": sorted(n for bit, n in CHARACTERISTICS.items() if chars & bit),
        "is_dll": bool(chars & 0x2000),
        "sections": sections,
        "directories": [d for d in dirs if d["rva"]],
        "imports": [],
        "exports": None,
        "version_strings": {},
    }

    # Imports
    imp = dirs[1]
    if imp["rva"]:
        base = _rva_to_off(imp["rva"], sections)
        if base is not None:
            i = 0
            while True:
                o = base + i * 20
                if o + 20 > len(data):
                    break
                _oft, _ts, _fc, name_rva, fthunk = struct.unpack_from("<IIIII", data, o)
                if name_rva == 0 and fthunk == 0:
                    break
                dll = ""
                noff = _rva_to_off(name_rva, sections)
                if noff is not None:
                    dll = _read_cstr(data, noff)
                funcs: list = []
                thunk_rva = _oft or fthunk
                toff = _rva_to_off(thunk_rva, sections)
                if toff is not None and len(funcs) < max_imports:
                    j = 0
                    step = 8 if pe32plus else 4
                    while True:
                        t = toff + j * step
                        if t + step > len(data):
                            break
                        val = struct.unpack_from("<Q" if pe32plus else "<I", data, t)[0]
                        if val == 0:
                            break
                        if val & (1 << (63 if pe32plus else 31)):
                            funcs.append(f"ordinal:{val & 0xFFFF}")
                        else:
                            hoff = _rva_to_off(val & 0x7FFFFFFF, sections)
                            if hoff is not None:
                                funcs.append(_read_cstr(data, hoff + 2))
                        j += 1
                        if j >= max_imports:
                            break
                out["imports"].append({"dll": dll, "functions": funcs})
                i += 1

    # Exports
    exp = dirs[0]
    if exp["rva"]:
        eoff = _rva_to_off(exp["rva"], sections)
        if eoff is not None:
            _flags, _ts, _maj, _min, name_rva, ordinal_base, nfuncs, nnames, \
                af_rva, an_rva, ao_rva = struct.unpack_from("<IIHHIIIIIII", data, eoff)
            dll_name = ""
            noff = _rva_to_off(name_rva, sections)
            if noff is not None:
                dll_name = _read_cstr(data, noff)
            names = []
            for k in range(min(nnames, max_exports)):
                no = _rva_to_off(an_rva + 4 * k, sections)
                if no is None:
                    break
                fn_rva = struct.unpack_from("<I", data, no)[0]
                fo = _rva_to_off(fn_rva, sections)
                names.append(_read_cstr(data, fo) if fo is not None else f"#{k}")
            by_ord: dict[int, str] = {}
            for k in range(min(nnames, max_exports)):
                no = _rva_to_off(an_rva + 4 * k, sections)
                if no is None:
                    break
                idx = struct.unpack_from("<H", data, _rva_to_off(ao_rva + 2 * k, sections) or 0)[0]
                fn_rva = struct.unpack_from("<I", data, no)[0]
                fo = _rva_to_off(fn_rva, sections)
                if fo is not None:
                    by_ord[ordinal_base + idx] = _read_cstr(data, fo)
            out["exports"] = {
                "dll_name": dll_name,
                "ordinal_base": ordinal_base,
                "n_functions": nfuncs,
                "n_names": nnames,
                "names": names,
            }

    # Version resource
    res = dirs[2]
    if res["rva"]:
        out["version_strings"] = _parse_version_strings(res["rva"], min(res["size"], 0x10000), data, sections)

    return out


def version_from_strings(vs: dict) -> str | None:
    """'5.1.2600.6532' style FileVersion/ProductVersion if present."""
    for key in ("fileversion", "productversion"):
        v = vs.get(key, "")
        parts = [p for p in v.replace(",", ".").split(".") if p.strip().isdigit()]
        if len(parts) >= 2:
            return ".".join(parts[:4])
    return None


WINDOWS_MAP = [
    ((10, 0, 22000), "Windows 11"),
    ((10, 0), "Windows 10 / Server 2016+"),
    ((6, 3), "Windows 8.1 / Server 2012 R2"),
    ((6, 2), "Windows 8 / Server 2012"),
    ((6, 1), "Windows 7 / Server 2008 R2"),
    ((6, 0), "Windows Vista / Server 2008"),
    ((5, 2), "Windows XP x64 / Server 2003"),
    ((5, 1), "Windows XP"),
    ((5, 0), "Windows 2000"),
    ((4, 0), "Windows NT 4 / 95-era"),
]


def guess_windows(nt_ver: tuple[int, ...]) -> str | None:
    major, minor = nt_ver[0], nt_ver[1]
    build = nt_ver[2] if len(nt_ver) > 2 else None
    for key, name in WINDOWS_MAP:
        if (key[0], key[1]) != (major, minor):
            continue
        if len(key) == 3:  # disambiguator: only matches from this build onwards
            if build is None or build < key[2]:
                continue
            return f"{name} build {build}"
        extra = f" build {build}" if build is not None else ""
        return f"{name}{extra}"
    return None
