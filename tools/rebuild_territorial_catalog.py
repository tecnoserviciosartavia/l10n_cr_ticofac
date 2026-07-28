#!/usr/bin/env python3
"""Rebuild Costa Rica territorial CSV files from the official DTA publication.

The script intentionally preserves existing external IDs whenever the same
territorial code (or a moved district with the same name) can be identified.
This keeps partner and company addresses linked during module upgrades.
"""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from inspect_localidades_dbf import read_dbf


PROVINCES = {
    "1": ("San José", "base.state_SJ"),
    "2": ("Alajuela", "base.state_A"),
    "3": ("Cartago", "base.state_C"),
    "4": ("Heredia", "base.state_H"),
    "5": ("Guanacaste", "base.state_G"),
    "6": ("Puntarenas", "base.state_P"),
    "7": ("Limón", "base.state_L"),
}
LOWER_WORDS = {"de", "del", "la", "las", "los", "y"}
INEC_ADDRESS_CATEGORIES = {
    "BARRIO", "POBLADO", "CASERIO", "URBANIZACION", "RESIDENCIAL",
    "ASENTAMIENTO INFORMAL", "PRECARIO", "PROYECTO HABITACIONAL",
    "ASENTAMIENTO DEL IDA/INDER", "TERRITORIO/COMUNIDAD INDIGENA",
    "COMUNIDAD", "VILLA",
}
DISTRICT_RE = re.compile(
    r"^\s*(?P<canton>[1-7]\d{2})\s+(?P<number>\d{2})\s*:?\s+"
    r"(?P<name>[^:]+):(?P<tail>.*)$"
)
CANTON_RE = re.compile(r"^\s*CANTÓN\s+(?P<code>[1-7]\d{2}):\s*(?P<name>.+?)\s*$")
PLACE_RE = re.compile(r"\b(?:Barrios?|Poblados?|Caseríos?)[.:]\s*", re.IGNORECASE)
STOP_RE = re.compile(
    r"^\s*(?:Hojas?|Leyes?|Distritos?|Cantón|Provincia|Artículo|Notas?|\d{3}\s+\d{2}\s+Se declara desierto)\b",
    re.IGNORECASE,
)


@dataclass
class District:
    code: str
    name: str
    places: list[str] = field(default_factory=list)


@dataclass
class Canton:
    code: str
    name: str
    districts: list[District] = field(default_factory=list)


def normalize_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return re.sub(r"[^a-z0-9]+", "", value.encode("ascii", "ignore").decode().lower())


def smart_title(value: str) -> str:
    words = value.strip().title().split()
    return " ".join(
        word.lower() if index and word.lower() in LOWER_WORDS else word
        for index, word in enumerate(words)
    )


def clean_place(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" .,;")
    return smart_title(value)


def split_places(value: str) -> list[str]:
    value = re.sub(r"\s+", " ", value).strip(" .")
    value = re.sub(r"\s+y\s+(?=[^,]+$)", ", ", value, flags=re.IGNORECASE)
    return [clean_place(item) for item in value.split(",") if clean_place(item)]


def parse_dta(path: Path) -> dict[str, Canton]:
    lines = path.read_text(encoding="utf-8").replace("\f", "\n").splitlines()
    cantons: dict[str, Canton] = {}
    canton = None
    district = None
    place_buffer = ""

    def flush_places():
        nonlocal place_buffer
        if district and place_buffer:
            for place in split_places(place_buffer):
                if normalize_key(place) not in {normalize_key(item) for item in district.places}:
                    district.places.append(place)
        place_buffer = ""

    for raw_line in lines:
        line = raw_line.strip()
        canton_match = CANTON_RE.match(line)
        if canton_match:
            flush_places()
            code = canton_match.group("code")
            canton = Canton(code=code, name=smart_title(canton_match.group("name")))
            cantons[code] = canton
            district = None
            continue

        district_match = DISTRICT_RE.match(line)
        if (
            district_match
            and canton
            and district_match.group("canton") == canton.code
        ):
            flush_places()
            code = canton.code + district_match.group("number")
            district = District(code=code, name=smart_title(district_match.group("name")))
            canton.districts.append(district)
            tail = district_match.group("tail")
            place_match = PLACE_RE.search(tail)
            if place_match:
                place_buffer = tail[place_match.end() :]
            continue

        if not district:
            continue
        place_match = PLACE_RE.search(line)
        if place_match:
            flush_places()
            place_buffer = line[place_match.end() :]
        elif place_buffer and line and not STOP_RE.match(line):
            place_buffer += " " + line
        elif place_buffer:
            flush_places()
    flush_places()
    # INEC Localidades 2024: urbanización oficial no enumerada en la DTA.
    for item in cantons["303"].districts:
        if item.code == "30305" and "La Flor" not in item.places:
            item.places.append("La Flor")
            break
    return cantons


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def choose_unique(candidate: str, used: set[str]) -> str:
    # A dot makes Odoo interpret the prefix as another module name.
    candidate = candidate.replace(".", "_")
    if candidate not in used:
        used.add(candidate)
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in used:
        suffix += 1
    result = f"{candidate}_{suffix}"
    used.add(result)
    return result


def rebuild(dta_path: Path, data_dir: Path, write: bool, inec_dbf: Path | None = None):
    cantons = parse_dta(dta_path)
    districts_by_code = {
        district.code: district
        for canton in cantons.values()
        for district in canton.districts
    }
    if inec_dbf:
        for row in read_dbf(inec_dbf):
            category = row["DESCR_CAT"]
            name = row["NOMB_LOC"]
            if "Ã" in category:
                category = category.encode("latin1").decode("utf-8")
            if "Ã" in name:
                name = name.encode("latin1").decode("utf-8")
            district = districts_by_code.get(row["COD_UGED"])
            if not district or category not in INEC_ADDRESS_CATEGORIES or not name:
                continue
            known = {normalize_key(place) for place in district.places}
            if normalize_key(name) not in known:
                district.places.append(smart_title(name))
    districts = [district for canton in cantons.values() for district in canton.districts]
    if len(cantons) != 84:
        raise SystemExit(f"Se esperaban 84 cantones; se extrajeron {len(cantons)}")
    if len(districts) != 494:
        raise SystemExit(
            f"Se esperaban 494 distritos oficiales 2026; se extrajeron {len(districts)}"
        )

    county_path = data_dir / "res.country.county.csv"
    district_path = data_dir / "res.country.district.csv"
    neighborhood_path = data_dir / "res.country.neighborhood.csv"
    old_counties = read_csv(county_path)
    old_districts = read_csv(district_path)
    old_places = read_csv(neighborhood_path)

    province_by_state = {state: code for code, (_name, state) in PROVINCES.items()}
    old_county_id_by_code = {
        province_by_state[row["state_id:id"]] + row["code"].zfill(2): row["id"]
        for row in old_counties
    }
    old_county_code_by_id = {
        row["id"]: province_by_state[row["state_id:id"]] + row["code"].zfill(2)
        for row in old_counties
    }
    old_district_code_by_id = {
        row["id"]: old_county_code_by_id[row["county_id:id"]] + row["code"].zfill(2)
        for row in old_districts
    }
    old_district_id_by_code = {
        old_district_code_by_id[row["id"]]: row["id"] for row in old_districts
    }
    old_district_ids_by_name: dict[str, list[str]] = defaultdict(list)
    for row in old_districts:
        old_district_ids_by_name[normalize_key(row["name"])].append(row["id"])

    county_rows = []
    county_id_by_code = {}
    used_ids: set[str] = set()
    for code, canton in sorted(cantons.items()):
        external_id = old_county_id_by_code.get(code, f"county_cr_{code}")
        external_id = choose_unique(external_id, used_ids)
        county_id_by_code[code] = external_id
        county_rows.append(
            {
                "id": external_id,
                "code": code[-2:],
                "name": canton.name,
                "state_id:id": PROVINCES[code[0]][1],
            }
        )

    district_rows = []
    district_id_by_code = {}
    used_district_ids: set[str] = set()
    for canton in sorted(cantons.values(), key=lambda item: item.code):
        for district in canton.districts:
            external_id = old_district_id_by_code.get(district.code)
            if not external_id:
                name_matches = old_district_ids_by_name[normalize_key(district.name)]
                available = [item for item in name_matches if item not in used_district_ids]
                external_id = available[0] if len(available) == 1 else f"district_cr_{district.code}"
            external_id = choose_unique(external_id, used_district_ids)
            district_id_by_code[district.code] = external_id
            district_rows.append(
                {
                    "id": external_id,
                    "code": district.code[-2:],
                    "name": district.name,
                    "county_id:id": county_id_by_code[canton.code],
                }
            )

    old_places_by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in old_places:
        old_district_code = old_district_code_by_id.get(row["district_id:id"])
        if old_district_code:
            old_places_by_key[
                (old_district_code, normalize_key(row["name"]))
            ].append(row["id"])
    # Also preserve place IDs through district moves (Monteverde, Puerto Jiménez,
    # Río Cuarto) by looking at the reused district external ID.
    old_code_by_reused_id = {value: key for key, value in old_district_id_by_code.items()}

    place_rows = []
    used_place_ids: set[str] = set()
    for canton in sorted(cantons.values(), key=lambda item: item.code):
        for district in canton.districts:
            reused_id = district_id_by_code[district.code]
            source_code = old_code_by_reused_id.get(reused_id, district.code)
            # DTA sometimes only names the district seat and publishes no separate
            # Barrios/Poblados list; keep that seat selectable for addresses.
            places = district.places or [district.name]
            for index, place in enumerate(places, 1):
                candidates = old_places_by_key[
                    (source_code, normalize_key(place))
                ]
                external_id = next(
                    (item for item in candidates if item not in used_place_ids),
                    f"neighborhood_cr_{district.code}_{index:02d}",
                )
                external_id = choose_unique(external_id, used_place_ids)
                place_rows.append(
                    {
                        "id": external_id,
                        "code": f"{index:02d}",
                        "name": place,
                        "district_id:id": reused_id,
                    }
                )

    print(f"Cantones: {len(county_rows)}")
    print(f"Distritos: {len(district_rows)}")
    print(f"Barrios y poblados: {len(place_rows)}")
    print(
        "Distritos sin barrios/poblados:",
        ", ".join(
            f"{district.code} {district.name}"
            for district in districts
            if not district.places
        )
        or "ninguno",
    )
    print(
        "Cambios:",
        f"cantones {len(old_counties)} -> {len(county_rows)},",
        f"distritos {len(old_districts)} -> {len(district_rows)},",
        f"barrios/poblados {len(old_places)} -> {len(place_rows)}",
    )
    if write:
        write_csv(
            county_path, ["id", "code", "name", "state_id:id"], county_rows
        )
        write_csv(
            district_path, ["id", "code", "name", "county_id:id"], district_rows
        )
        write_csv(
            neighborhood_path,
            ["id", "code", "name", "district_id:id"],
            place_rows,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dta_text", type=Path)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--inec-dbf", type=Path)
    args = parser.parse_args()
    rebuild(args.dta_text, args.data_dir, args.write, args.inec_dbf)


if __name__ == "__main__":
    main()
