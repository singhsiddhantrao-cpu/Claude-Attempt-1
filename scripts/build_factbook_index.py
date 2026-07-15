"""Regenerate data/factbook_index.json, used by census_agent.py for religion lookups.

The CIA World Factbook JSON mirror (https://github.com/factbook/factbook.json)
stores one file per country at <region-dir>/<gec-code>.json, where the GEC code
is the (retired) US FIPS 10-4 code, not ISO 3166. This script joins the
open "datasets/country-codes" table (ISO alpha-3 <-> FIPS) against the mirror,
probing each region directory to find where every country's file actually
lives, and writes the resulting {iso3: {gec, region, name}} index.

Run it only when the mirror reorganizes or new countries appear:
    python scripts/build_factbook_index.py
"""

import csv
import io
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CODES_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/country-codes/main/data/country-codes.csv"
)
FACTBOOK_RAW_BASE = "https://raw.githubusercontent.com/factbook/factbook.json/master"

REGION_DIRS = [
    "africa",
    "antarctica",
    "australia-oceania",
    "central-america-n-caribbean",
    "central-asia",
    "east-n-southeast-asia",
    "europe",
    "middle-east",
    "north-america",
    "oceans",
    "south-america",
    "south-asia",
    "world",
]

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "factbook_index.json"


def _url_exists(url: str) -> bool:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status == 200
    except Exception:
        return False


def _locate(iso3: str, fips: str, name: str) -> tuple[str, dict] | None:
    gec = fips.strip().lower()
    for region in REGION_DIRS:
        if _url_exists(f"{FACTBOOK_RAW_BASE}/{region}/{gec}.json"):
            return iso3, {"gec": gec, "region": region, "name": name}
    return None


def main() -> None:
    with urllib.request.urlopen(CODES_CSV_URL, timeout=30) as response:
        rows = list(csv.DictReader(io.TextIOWrapper(response, encoding="utf-8")))

    candidates = [
        (row["ISO3166-1-Alpha-3"], row["FIPS"], row["UNTERM English Short"] or row["official_name_en"])
        for row in rows
        if row["ISO3166-1-Alpha-3"] and row["FIPS"]
    ]

    index: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=16) as pool:
        for result in pool.map(lambda args: _locate(*args), candidates):
            if result:
                iso3, entry = result
                index[iso3] = entry

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(dict(sorted(index.items())), indent=2) + "\n")
    print(f"Wrote {len(index)} of {len(candidates)} countries to {OUT_PATH}")


if __name__ == "__main__":
    main()
