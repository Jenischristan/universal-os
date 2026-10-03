"""Tests for the pure-python PE parser (synthetic minimal PE)."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from universal_os import pefile  # noqa: E402


def build_minimal_pe(exports=("NtCreateFile", "NtClose")) -> bytes:
    """Craft a tiny but valid PE32 with an export directory."""
    SECT_RVA = 0x1000
    SECT_RAW = 0x400
    e_lfanew = 0x80
    pe_off = e_lfanew

    def coff(machine=0x014C, nsec=1, opt_size=224, chars=0x2102):
        return struct.pack("<HHIIIHH", machine, nsec, 0, 0, 0, opt_size, chars)

    def opt32(subsystem=2, export_rva=0, export_size=0):
        """PE32 optional header, 224 bytes, exact field offsets."""
        d = bytearray(224)
        struct.pack_into("<H", d, 0, 0x10B)       # magic (PE32)
        d[2], d[3] = 1, 0                          # linker 1.0
        struct.pack_into("<I", d, 4, 0x200)        # SizeOfCode
        struct.pack_into("<I", d, 16, SECT_RVA)    # AddressOfEntryPoint
        struct.pack_into("<I", d, 20, SECT_RVA)    # BaseOfCode
        struct.pack_into("<I", d, 24, SECT_RVA)    # BaseOfData
        struct.pack_into("<I", d, 28, 0x400000)    # ImageBase
        struct.pack_into("<I", d, 32, 0x40)        # SectionAlignment
        struct.pack_into("<I", d, 36, 0x100)       # FileAlignment
        struct.pack_into("<H", d, 40, 4)           # MajorOSVersion
        struct.pack_into("<H", d, 48, 5)           # MajorSubsystemVersion
        struct.pack_into("<H", d, 50, 1)           # MinorSubsystemVersion
        struct.pack_into("<I", d, 56, 0x4000)      # SizeOfImage
        struct.pack_into("<I", d, 60, 0x400)       # SizeOfHeaders
        struct.pack_into("<H", d, 68, subsystem)   # Subsystem
        struct.pack_into("<I", d, 92, 16)          # NumberOfRvaAndSizes
        struct.pack_into("<II", d, 96, export_rva, export_size)  # DataDirectory[0]
        return bytes(d)

    def section(name=".text", vsize=0x800, vaddr=SECT_RVA, rawsize=0x800, rawoff=SECT_RAW):
        return (name.encode().ljust(8, b"\x00")
                + struct.pack("<IIII", vsize, vaddr, rawsize, rawoff)
                + struct.pack("<IIHHI", 0, 0, 0, 0, 0x60000020))

    # ---- export directory at RVA SECT_RVA, raw SECT_RAW
    names = [n.encode() for n in exports]
    name_blob = b"\x00".join(names) + b"\x00"
    dll_name = b"testdll\x00"
    dll_name_rva = SECT_RVA + 40
    names_ptr_rva = dll_name_rva + len(dll_name)          # AddressOfNames array
    names_rva = names_ptr_rva + 4 * len(names)            # the name strings themselves
    ord_off = names_rva + len(name_blob)                  # AddressOfNameOrdinals
    dir_struct = struct.pack("<IIHHIIIIIII",
                             0, 0, 0, 0,
                             dll_name_rva, 1, len(exports), len(exports),
                             0, names_ptr_rva, ord_off)
    name_ptrs = b"".join(struct.pack("<I", names_rva + off)
                         for off in (sum(len(n) + 1 for n in names[:i]) for i in range(len(names))))
    ordinals = b"".join(struct.pack("<H", i) for i in range(len(names)))

    body = bytearray(0x800)
    body[0:len(dir_struct)] = dir_struct
    body[40:40 + len(dll_name)] = dll_name
    body[names_ptr_rva - SECT_RVA:names_ptr_rva - SECT_RVA + len(name_ptrs)] = name_ptrs
    body[names_rva - SECT_RVA:names_rva - SECT_RVA + len(name_blob)] = name_blob
    body[ord_off - SECT_RVA:ord_off - SECT_RVA + len(ordinals)] = ordinals

    img = bytearray(SECT_RAW + 0x800)
    img[0:2] = b"MZ"
    struct.pack_into("<I", img, 0x3C, e_lfanew)
    img[pe_off:pe_off + 4] = b"PE\x00\x00"
    c = coff()
    img[pe_off + 4:pe_off + 4 + len(c)] = c
    o = opt32(export_rva=SECT_RVA, export_size=len(dir_struct) + len(dll_name) + len(name_blob) + len(ordinals))
    img[pe_off + 24:pe_off + 24 + len(o)] = o
    s = section()
    img[pe_off + 24 + len(o):pe_off + 24 + len(o) + len(s)] = s
    img[SECT_RAW:SECT_RAW + 0x800] = body
    return bytes(img)


def test_parse_minimal_pe(tmp_path):
    p = tmp_path / "test.dll"
    p.write_bytes(build_minimal_pe())
    info = pefile.parse_pe(p)
    assert info["machine"] == "i386"
    assert info["bits"] == 32
    assert info["subsystem"] == "windows-gui"
    assert info["is_dll"] is True
    assert info["os_version"] == "4.0"
    exp = info["exports"]
    assert exp is not None
    assert exp["n_functions"] == 2
    assert set(exp["names"]) == {"NtCreateFile", "NtClose"}


def test_not_pe(tmp_path):
    p = tmp_path / "nope.bin"
    p.write_bytes(b"hello world, not an executable")
    try:
        pefile.parse_pe(p)
        assert False, "should have raised"
    except pefile.PEError:
        pass


def test_guess_windows():
    assert "Windows XP" in pefile.guess_windows((5, 1, 2600))
    assert "Windows 7" in pefile.guess_windows((6, 1, 7601))
    assert "Windows 10" in pefile.guess_windows((10, 0, 19045))
    assert "Windows 11" in pefile.guess_windows((10, 0, 22631))


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_parse_minimal_pe(Path(td))
        test_not_pe(Path(td))
    test_guess_windows()
    print("pefile tests OK")
