"""
BoM cumulative rainfall forecast backend.

Data source:
    BoM anonymous FTP:
    /anon/gen/fwo/IDQ11295.xml

Project-to-BoM forecast mapping:
    Moogerah     -> Boonah
    Warrill View -> Boonah
    Mount Walker -> Laidley
    Rosewood     -> Ipswich
    Lyons        -> Ipswich
    Ipswich      -> Ipswich

Cumulative periods are retained from the previous Elders workflow:
    1 Day Forecast = Today + Tomorrow
    3 Day Forecast = Today through Today + 3 days
    5 Day Forecast = Today through Today + 5 days

Forecast rainfall ranges are stored against actual calendar dates.
If the latest BoM XML omits today's precipitation range, a previously
cached valid forecast for the same location and date is retained.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from ftplib import FTP, all_errors
from io import BytesIO
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo


# =========================================================
# BoM FTP configuration
# =========================================================

FTP_HOST = "ftp.bom.gov.au"
FTP_DIRECTORY = "/anon/gen/fwo"
FTP_FILENAME = "IDQ11295.xml"
FTP_TIMEOUT = 30

BRISBANE_TIMEZONE = ZoneInfo(
    "Australia/Brisbane"
)

CACHE_PATH = (
    Path(__file__).parent
    / "data"
    / "bom_forecast_cache.json"
)


# =========================================================
# Fixed project-to-BoM forecast mapping
# =========================================================

FORECAST_LOCATION_MAP = [
    {
        "station_number": "040135",
        "location": "Moogerah",
        "bom_location": "Boonah",
        "bom_aac": "QLD_PT045",
    },
    {
        "station_number": "540387",
        "location": "Warrill View",
        "bom_location": "Boonah",
        "bom_aac": "QLD_PT045",
    },
    {
        "station_number": "540574",
        "location": "Mount Walker",
        "bom_location": "Laidley",
        "bom_aac": "QLD_PT113",
    },
    {
        "station_number": "540503",
        "location": "Rosewood",
        "bom_location": "Ipswich",
        "bom_aac": "QLD_PT014",
    },
    {
        "station_number": "040793",
        "location": "Lyons",
        "bom_location": "Ipswich",
        "bom_aac": "QLD_PT014",
    },
    {
        "station_number": "540250",
        "location": "Ipswich",
        "bom_location": "Ipswich",
        "bom_aac": "QLD_PT014",
    },
]

REQUIRED_AACS = {
    item["bom_aac"]
    for item in FORECAST_LOCATION_MAP
}


# =========================================================
# Rainfall-range parsing
# =========================================================

NUMBER_PATTERN = re.compile(
    r"\d+(?:\.\d+)?"
)


class ForecastError(RuntimeError):
    """Raised when BoM forecast retrieval or parsing fails."""


def clean(value) -> str:
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value).replace(
            "\xa0",
            " ",
        ),
    ).strip()


def local_name(tag: str) -> str:
    """
    Return an XML tag name without its namespace.
    """

    return tag.rsplit(
        "}",
        1,
    )[-1]


def parse_datetime(value):
    """
    Parse BoM ISO timestamps.

    Returns None when the supplied value is blank or invalid.
    """

    if not value:
        return None

    try:
        return datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00",
            )
        )

    except ValueError:
        return None


def parse_rain_range(
    value,
) -> tuple[float | None, float | None]:
    """
    Parse rainfall ranges such as:

        0 to 8 mm
        2 - 10 mm
        3 mm

    Missing fields return:

        (None, None)
    """

    text = clean(value)

    if not text:
        return None, None

    numbers = [
        float(number)
        for number in NUMBER_PATTERN.findall(
            text
        )
    ]

    if len(numbers) == 1:
        return numbers[0], numbers[0]

    if len(numbers) == 2:
        return numbers[0], numbers[1]

    return None, None


def format_mm(value: float) -> str:
    """
    Format rainfall without unnecessary trailing zeroes.
    """

    return (
        f"{float(value):.2f}"
        .rstrip("0")
        .rstrip(".")
    )


def format_range(
    minimum: float,
    maximum: float,
) -> str:
    """
    Convert numerical bounds into the existing app format.
    """

    if minimum == maximum:
        return f"{format_mm(minimum)} mm"

    return (
        f"{format_mm(minimum)} - "
        f"{format_mm(maximum)} mm"
    )


# =========================================================
# XML utility functions
# =========================================================

def first_text_by_name(
    root,
    name,
):
    """
    Find the first XML element with the specified local name.
    """

    for element in root.iter():
        if local_name(element.tag) != name:
            continue

        text = clean(element.text)

        if text:
            return text

    return None


def direct_children_by_name(
    parent,
    name,
):
    """
    Return direct child elements matching a local XML tag name.
    """

    return [
        child
        for child in list(parent)
        if local_name(child.tag) == name
    ]


def find_child_by_type(
    parent,
    element_name,
    type_name,
):
    """
    Find a direct child such as:

        <element type="precipitation_range">
        <text type="probability_of_precipitation">
    """

    for child in direct_children_by_name(
        parent,
        element_name,
    ):
        if child.get("type") == type_name:
            return child

    return None


# =========================================================
# FTP retrieval
# =========================================================

def download_forecast_xml() -> bytes:
    """
    Download IDQ11295.xml from BoM anonymous FTP.
    """

    buffer = BytesIO()

    try:
        with FTP(
            host=FTP_HOST,
            timeout=FTP_
