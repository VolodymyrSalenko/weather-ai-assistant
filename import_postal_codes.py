"""Import Swiss postal code locations from geo.admin.ch into the PostgreSQL postal_codes table."""

from __future__ import annotations

import csv
import io
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zipfile import ZipFile

import psycopg
from dotenv import load_dotenv


# Official swisstopo / geo.admin.ch layer:
# ch.swisstopo-vd.ortschaftenverzeichnis_plz
#
# This direct WGS84 CSV ZIP asset comes from the geo.admin.ch STAC API. If the
# download format changes later, this is the main value to adjust.
SOURCE_URL = (
    "https://data.geo.admin.ch/ch.swisstopo-vd.ortschaftenverzeichnis_plz/"
    "ortschaftenverzeichnis_plz/ortschaftenverzeichnis_plz_4326.csv.zip"
)
SOURCE_LAYER = "ch.swisstopo-vd.ortschaftenverzeichnis_plz"
STAC_ITEMS_URL = (
    "https://data.geo.admin.ch/api/stac/v0.9/collections/"
    "ch.swisstopo-vd.ortschaftenverzeichnis_plz/items"
)


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS postal_codes (
    id SERIAL PRIMARY KEY,
    postal_code VARCHAR(4) NOT NULL,
    city TEXT NOT NULL,
    canton VARCHAR(2),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_UNIQUE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS postal_codes_postal_code_city_key
ON postal_codes (postal_code, city);
"""

INSERT_SQL = """
INSERT INTO postal_codes (
    postal_code,
    city,
    canton,
    latitude,
    longitude,
    source
)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (postal_code, city) DO NOTHING
RETURNING id;
"""


def download_source() -> bytes:
    """Download the official source file from geo.admin.ch."""
    request = Request(
        SOURCE_URL,
        headers={"User-Agent": "anw-weather-ai-bot-postal-code-importer/1.0"},
    )

    with urlopen(request, timeout=60) as response:
        return response.read()


def extract_csv_text(source_data: bytes) -> str:
    """Extract CSV text from a ZIP download, or read plain CSV bytes."""
    if SOURCE_URL.lower().endswith(".zip"):
        with ZipFile(io.BytesIO(source_data)) as archive:
            csv_names = [
                name
                for name in archive.namelist()
                if name.lower().endswith(".csv") and not name.endswith("/")
            ]

            if not csv_names:
                raise RuntimeError("The downloaded ZIP file does not contain a CSV file.")

            with archive.open(csv_names[0]) as csv_file:
                return csv_file.read().decode("utf-8-sig")

    return source_data.decode("utf-8-sig")


def get_value(row: dict[str, Any], *names: str) -> str:
    """Read the first matching non-empty CSV value from possible column names."""
    lower_row = {key.lower(): value for key, value in row.items() if key}

    for name in names:
        value = row.get(name)
        if value:
            return str(value).strip()

        value = lower_row.get(name.lower())
        if value:
            return str(value).strip()

    return ""


def parse_float(value: str) -> float | None:
    if not value:
        return None

    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def parse_rows(csv_text: str) -> list[tuple[str, str, str | None, float | None, float | None, str]]:
    """Parse postal code rows from the official CSV export."""
    text_io = io.StringIO(csv_text)

    try:
        dialect = csv.Sniffer().sniff(csv_text[:4096], delimiters=";,")
        reader = csv.DictReader(text_io, dialect=dialect)
    except csv.Error:
        text_io.seek(0)
        reader = csv.DictReader(text_io, delimiter=";")

    rows = []
    seen: set[tuple[str, str]] = set()

    for row in reader:
        # Current official CSV columns include:
        # Ortschaftsname;PLZ4;...;Kantonskuerzel;...;E;N
        city = get_value(row, "Ortschaftsname", "city", "name")
        postal_code = get_value(row, "PLZ4", "postal_code", "postcode", "zip")

        if postal_code.isdigit() and len(postal_code) <= 4:
            postal_code = postal_code.zfill(4)

        if not city or not (postal_code.isdigit() and len(postal_code) == 4):
            continue

        key = (postal_code, city)
        if key in seen:
            continue

        seen.add(key)

        canton = get_value(row, "Kantonsk\u00fcrzel", "canton", "kanton") or None

        # In the WGS84 CSV, E is longitude and N is latitude.
        longitude = parse_float(get_value(row, "E", "longitude", "lon", "lng"))
        latitude = parse_float(get_value(row, "N", "latitude", "lat"))

        rows.append((postal_code, city, canton, latitude, longitude, SOURCE_LAYER))

    return rows


def create_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cursor:
        cursor.execute(CREATE_TABLE_SQL)
        cursor.execute(CREATE_UNIQUE_INDEX_SQL)


def insert_rows(
    conn: psycopg.Connection,
    rows: list[tuple[str, str, str | None, float | None, float | None, str]],
) -> int:
    inserted = 0

    with conn.cursor() as cursor:
        for row in rows:
            cursor.execute(INSERT_SQL, row)
            if cursor.fetchone() is not None:
                inserted += 1

    return inserted


def main() -> None:
    load_dotenv()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set in .env.")

    try:
        source_data = download_source()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not download postal code data from {SOURCE_URL}") from exc

    rows = parse_rows(extract_csv_text(source_data))
    if not rows:
        raise RuntimeError(
            "No postal code rows were parsed. Check SOURCE_URL or the CSV column names."
        )

    with psycopg.connect(database_url) as conn:
        create_table(conn)
        inserted = insert_rows(conn, rows)

    print(f"Inserted {inserted} postal code rows into postal_codes.")
    print(f"Source: {SOURCE_LAYER}")
    print(f"Source URL: {SOURCE_URL}")


if __name__ == "__main__":
    main()
