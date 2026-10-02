"""Inspect legacy Chromium block-cache entries for one Fanqie book.

The output includes cache addresses and sizes but redacts query strings so
signed request credentials never leave the local machine.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


CACHE_ROOT = Path("data/browser/fanqie/user_data/Default/Cache/Cache_Data")
BOOK_ID = "7656344274241326104"


def safe_key(value: str) -> str:
    marker = value.find("https://kol.fanqieopen.com/")
    if marker >= 0:
        prefix, url = value[:marker], value[marker:]
        parsed = urlsplit(url)
        return prefix + urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return value[:240]


def main() -> None:
    data = (CACHE_ROOT / "data_1").read_bytes()
    records = []
    for block in range((len(data) - 8192) // 256):
        offset = 8192 + block * 256
        raw = data[offset : offset + 256]
        if len(raw) != 256:
            continue
        key_len = struct.unpack_from("<i", raw, 32)[0]
        if not 0 < key_len < 16_384:
            continue
        long_key = struct.unpack_from("<I", raw, 36)[0]
        inline = raw[96 : 96 + min(key_len, 160)].split(b"\0", 1)[0]
        try:
            key = inline.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if BOOK_ID not in key or "/api/platform/content/" not in key:
            continue
        records.append(
            {
                "block": block,
                "hash": struct.unpack_from("<I", raw, 0)[0],
                "next": f"0x{struct.unpack_from('<I', raw, 4)[0]:08x}",
                "state": struct.unpack_from("<i", raw, 20)[0],
                "key_len": key_len,
                "long_key": f"0x{long_key:08x}",
                "data_size": list(struct.unpack_from("<4i", raw, 40)),
                "data_addr": [f"0x{x:08x}" for x in struct.unpack_from("<4I", raw, 56)],
                "key": safe_key(key),
            }
        )
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
