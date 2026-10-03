"""Minimal PPM (P6) -> PNG converter, pure Python.

QEMU's screendump writes PPM; PNG is what both humans and vision models want.
No Pillow dependency: we emit a valid PNG with zlib ourselves.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def ppm_to_png_bytes(ppm: bytes) -> bytes:
    if ppm[:2] != b"P6":
        raise ValueError("not a binary PPM (P6)")
    # header: P6\n<whitespace-w> <h>\n<maxval>\n
    fields: list[int] = []
    i = 2
    while len(fields) < 3:
        while i < len(ppm) and ppm[i:i + 1].isspace():
            i += 1
        if ppm[i:i + 1] == b"#":  # comment runs to end of line
            while i < len(ppm) and ppm[i:i + 1] != b"\n":
                i += 1
            continue
        j = i
        while j < len(ppm) and ppm[j:j + 1].isdigit():
            j += 1
        if j == i:
            raise ValueError("malformed PPM header")
        fields.append(int(ppm[i:j]))
        i = j
    i += 1  # single whitespace after maxval
    w, h, _maxv = fields
    raw = ppm[i:i + w * h * 3]
    if len(raw) < w * h * 3:
        raise ValueError("truncated PPM pixel data")

    scan = b"".join(b"\x00" + raw[y * w * 3:(y + 1) * w * 3] for y in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(scan, 6))
            + _png_chunk(b"IEND", b""))


def ppm_file_to_png(ppm_path: str | Path, png_path: str | Path) -> tuple[int, int]:
    data = Path(ppm_path).read_bytes()
    png = ppm_to_png_bytes(data)
    Path(png_path).write_bytes(png)
    # re-read dims for the return value
    fields = []
    i = 2
    while len(fields) < 2:
        while data[i:i + 1].isspace():
            i += 1
        j = i
        while data[j:j + 1].isdigit():
            j += 1
        fields.append(int(data[i:j]))
        i = j
    return fields[0], fields[1]
