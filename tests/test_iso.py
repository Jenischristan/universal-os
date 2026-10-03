"""Tests for the ISO9660/Joliet reader (synthetic minimal ISO)."""
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from universal_os import isofs  # noqa: E402

SECTOR = 2048


def make_dir_record(name: bytes, lba: int, size: int, is_dir: bool) -> bytes:
    """Real ISO9660 directory record: 33-byte header + name, padded to even length."""
    flags = 0x02 if is_dir else 0x00
    nlen = len(name)
    rec_len = 33 + nlen
    if rec_len % 2:
        rec_len += 1
    rec = struct.pack("<B", rec_len)
    rec += struct.pack("<B", 0)              # ext attr len
    rec += struct.pack("<I", lba)            # LBA LE
    rec += struct.pack("<I", lba)            # LBA BE
    rec += struct.pack("<I", size)           # size LE
    rec += struct.pack("<I", size)           # size BE
    rec += struct.pack("<BBBBBBb", 126, 1, 1, 0, 0, 0, 0)  # recording date (7 bytes)
    rec += struct.pack("<B", flags)
    rec += struct.pack("<B", 0)              # file unit size
    rec += struct.pack("<B", 0)              # interleave gap
    rec += struct.pack("<HH", 1, 1)          # volume sequence (both-endian)
    rec += struct.pack("<B", nlen)
    rec += name
    if (33 + nlen) % 2:
        rec += b"\x00"                       # padding byte
    assert len(rec) == rec_len, (len(rec), rec_len)
    return rec


def build_minimal_iso() -> bytes:
    nsec = 64
    img = bytearray(nsec * SECTOR)

    root_rec = make_dir_record(b"\x00", 17, SECTOR, True)
    pvd = bytearray(SECTOR)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[7] = 1
    pvd[40:72] = b"TESTVOLUME".ljust(32)
    pvd[156:156 + len(root_rec)] = root_rec
    img[16 * SECTOR:17 * SECTOR] = pvd

    # dir at LBA 17: '.', '..', 'SOURCES' (dir), 'AUTORUN.INF' (file)
    d = bytearray(SECTOR)
    rec_dot = make_dir_record(b"\x00", 17, SECTOR, True)
    rec_dotdot = make_dir_record(b"\x01", 16, SECTOR, True)
    rec_src = make_dir_record(b"SOURCES", 18, SECTOR, True)
    rec_file = make_dir_record(b"AUTORUN.INF;1", 19, 11, False)
    off = 0
    for r in (rec_dot, rec_dotdot, rec_src, rec_file):
        d[off:off + len(r)] = r
        off += len(r)
    img[17 * SECTOR:18 * SECTOR] = d

    # SOURCES dir at LBA 18: '.', '..', 'CVERSION.INI'
    d2 = bytearray(SECTOR)
    off = 0
    for r in (make_dir_record(b"\x00", 18, SECTOR, True),
              make_dir_record(b"\x01", 17, SECTOR, True),
              make_dir_record(b"CVERSION.INI;1", 20, 20, False)):
        d2[off:off + len(r)] = r
        off += len(r)
    img[18 * SECTOR:19 * SECTOR] = d2

    # files
    img[19 * SECTOR:19 * SECTOR + 11] = b"[autorun]\n\n"
    img[20 * SECTOR:20 * SECTOR + 20] = b"BuildInfo=12345ABCDE\n"
    return bytes(img)


def test_iso_listing_and_read():
    with tempfile.TemporaryDirectory() as td:
        iso_path = Path(td) / "mini.iso"
        iso_path.write_bytes(build_minimal_iso())
        with isofs.IsoImage(iso_path) as iso:
            assert iso.volume_id.strip() == "TESTVOLUME"
            top = {e["name"] for e in iso.listdir("/")}
            assert "SOURCES" in top and "AUTORUN.INF" in top
            src = {e["name"] for e in iso.listdir("/SOURCES")}
            assert "CVERSION.INI" in src
            data = iso.read_file("/AUTORUN.INF").decode()
            assert data.startswith("[autorun]")
            data2 = iso.read_file("/SOURCES/CVERSION.INI").decode()
            assert "BuildInfo" in data2
            walk = iso.walk("/", depth=2)
            assert any(e["path"] == "/SOURCES/CVERSION.INI" for e in walk)


def test_missing_file_raises():
    with tempfile.TemporaryDirectory() as td:
        iso_path = Path(td) / "mini.iso"
        iso_path.write_bytes(build_minimal_iso())
        with isofs.IsoImage(iso_path) as iso:
            try:
                iso.read_file("/NOPE.DLL")
                assert False, "should raise"
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    test_iso_listing_and_read()
    test_missing_file_raises()
    print("isofs tests OK")
