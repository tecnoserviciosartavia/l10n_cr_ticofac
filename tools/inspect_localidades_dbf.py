#!/usr/bin/env python3
"""Inspect INEC's Localidades DBF using only Python's standard library."""

from __future__ import annotations

import collections
import struct
import sys
from pathlib import Path


def read_dbf(path: Path):
    with path.open("rb") as stream:
        header = stream.read(32)
        record_count, header_length, record_length = struct.unpack(
            "<xxxxIHH20x", header
        )
        fields = []
        for _index in range((header_length - 33) // 32):
            descriptor = stream.read(32)
            name = descriptor[:11].split(b"\0", 1)[0].decode("ascii")
            fields.append((name, descriptor[16]))
        stream.seek(header_length)
        for _index in range(record_count):
            record = stream.read(record_length)
            if not record or record[:1] == b"*":
                continue
            offset = 1
            values = {}
            for name, length in fields:
                raw_value = record[offset : offset + length]
                offset += length
                values[name] = raw_value.decode("latin-1").strip()
            yield values


def main():
    records = list(read_dbf(Path(sys.argv[1])))
    district_codes = {row["COD_UGED"] for row in records if row["COD_UGED"]}
    print(f"Registros: {len(records)}")
    print(f"Distritos: {len(district_codes)}")
    print("Categorías:")
    for category, count in collections.Counter(
        (row["DESCR_CAT"], row["CAT_PUNTO"]) for row in records
    ).most_common():
        print(f"  {category}: {count}")
    print("Muestra:")
    for row in records[:20]:
        print(
            row["COD_UGED"],
            row["NOMB_UGEP"],
            row["NOMB_UGEC"],
            row["NOMB_UGED"],
            row["DESCR_CAT"],
            row["NOMB_LOC"],
            row["COD_SNIT"],
        )


if __name__ == "__main__":
    main()
