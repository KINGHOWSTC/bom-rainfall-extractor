"""
Independent river-level add-on for BoM product IDQ60286.

Retrieval order:
1. BoM anonymous FTP: IDQ60286.html
2. BoM HTTPS product page as a fallback

The downloaded HTML product is parsed to extract the selected river gauges.
This module does not import or modify the rainfall backend.
"""

from __future__ import annotations

import io
import re
from ftplib import FTP, all_errors

import requests
from bs4 import BeautifulSoup


# =========================================================
# BoM product configuration
# =========================================================

RIVER_PRODUCT = "IDQ60286"
RIVER_FILENAME = f"{RIVER_PRODUCT}.html"

FTP_HOST = "ftp.bom.gov.au"
FTP_DIRECTORY = "/anon/gen/fwo"
FTP_TIMEOUT = 30

RIVER_URL = (
    "https://www.bom.gov.au/cgi-bin/"
    f"wrap_fwo.pl?{RIVER_PRODUCT}.html"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-AU,en;q=0.9",
}


# =========================================================
# Parsing patterns
# =========================================================

GAUGE_RE = re.compile(
    r"IDQ65389\.(\d{6})\.(?:plt|tbl)\.shtml",
    re.IGNORECASE,
)

ISSUED_RE = re.compile(
    r"Issued at\s+"
    r"(\d{1,2}:\d{2}\s*(?:AM|PM)\s+"
    r"(?:AEST|EST)\s+\w+\s+\d{1,2}\s+\w+\s+\d{4})",
    re.IGNORECASE,
)


# =========================================================
# Required gauges
# =========================================================

TARGET_GAUGES = [
    {
        "gauge": "540065",
        "location": "Peak Crossing",
    },
    {
        "gauge": "540062",
        "location": "Loamside",
    },
    {
        "gauge": "540057",
        "location": "Kalbar",
    },
    {
        "gauge": "540387",
        "location": "Harrisville",
    },
    {
        "gauge": "540180",
        "location": "Amberley",
    },
    {
        "gauge": "540157",
        "location": "Adams Bridge",
    },
    {
        "gauge": "540388",
        "location": "Rosewood",
    },
    {
        "gauge": "540147",
        "location": "Five Mile Bridge",
    },
    {
        "gauge": "540504",
        "location": "Walloon",
    },
    {
        "gauge": "040836",
        "location": "One Mile Bridge",
    },
    {
        "gauge": "540250",
        "location": "Hancocks Bridge",
    },
    {
        "gauge": "040831",
        "location": "Ipswich",
    },
]

TARGET_BY_GAUGE = {
    item["gauge"]: item
    for item in TARGET_GAUGES
}


# Records the most recent successful retrieval method.
LAST_RETRIEVAL_METHOD = None


class RiverLevelError(RuntimeError):
    """Raised when river-level retrieval or parsing fails."""


def clean(value: str) -> str:
    """Collapse repeated whitespace and remove non-breaking spaces."""

    return re.sub(
        r"\s+",
        " ",
        value.replace("\xa0", " "),
    ).strip()


def decode_product(raw: bytes) -> str:
    """Decode a BoM HTML product using common encodings."""

    if not raw:
        raise RiverLevelError(
            f"The retrieved {RIVER_FILENAME} file was empty."
        )

    try:
        return raw.decode("utf-8-sig")

    except UnicodeDecodeError:
        return raw.decode(
            "windows-1252",
            errors="replace",
        )


def validate_product(html: str) -> str:
    """Confirm that the retrieved content is the expected product."""

    if not html.strip():
        raise RiverLevelError(
            f"The retrieved {RIVER_FILENAME} file was empty."
        )

    # Some product versions may not display the ID in visible text,
    # so also accept the expected river-height table structure.
    soup = BeautifulSoup(html, "lxml")

    has_product_id = RIVER_PRODUCT in html
    has_river_table = soup.select_one("table.rhb") is not None

    if not has_product_id and not has_river_table:
        raise RiverLevelError(
            "The retrieved file was not the expected "
            f"{RIVER_PRODUCT} river-height bulletin."
        )

    return html


# =========================================================
# FTP retrieval
# =========================================================

def fetch_river_html_from_ftp() -> str:
    """
    Retrieve IDQ60286.html from the BoM anonymous FTP service.
    """

    buffer = io.BytesIO()

    try:
        with FTP(
            host=FTP_HOST,
            timeout=FTP_TIMEOUT,
        ) as ftp:
            # Anonymous login.
            ftp.login()

            # Passive mode is normally better for cloud hosting,
            # NAT and firewall environments.
            ftp.set_pasv(True)

            ftp.cwd(FTP_DIRECTORY)

            ftp.retrbinary(
                f"RETR {RIVER_FILENAME}",
                buffer.write,
            )

    except all_errors as exc:
        raise RiverLevelError(
            f"BoM FTP retrieval failed for "
            f"{RIVER_FILENAME}: {exc}"
        ) from exc

    html = decode_product(
        buffer.getvalue()
    )

    return validate_product(html)


# =========================================================
# HTTPS fallback
# =========================================================

def fetch_river_html_from_https() -> str:
    """
    Retrieve IDQ60286 through the BoM HTTPS product page.

    This is used only when anonymous FTP is unavailable.
    """

    try:
        response = requests.get(
            RIVER_URL,
            headers=HEADERS,
            timeout=30,
        )

    except requests.RequestException as exc:
        raise RiverLevelError(
            f"BoM HTTPS retrieval failed: {exc}"
        ) from exc

    if response.status_code == 403:
        raise RiverLevelError(
            "BoM blocked the automatic river-level "
            "request with HTTP 403."
        )

    try:
        response.raise_for_status()

    except requests.RequestException as exc:
        raise RiverLevelError(
            "BoM HTTPS retrieval failed with "
            f"HTTP {response.status_code}: {exc}"
        ) from exc

    return validate_product(
        response.text
    )


def fetch_river_html() -> str:
    """
    Retrieve the latest river-height product.

    Retrieval order:
    1. BoM anonymous FTP
    2. BoM HTTPS fallback
    """

    global LAST_RETRIEVAL_METHOD

    ftp_error = None

    try:
        html = fetch_river_html_from_ftp()

        LAST_RETRIEVAL_METHOD = (
            f"BoM anonymous FTP {RIVER_FILENAME}"
        )

        return html

    except RiverLevelError as exc:
        ftp_error = str(exc)

    try:
        html = fetch_river_html_from_https()

        LAST_RETRIEVAL_METHOD = (
            f"BoM HTTPS fallback {RIVER_PRODUCT}"
        )

        return html

    except RiverLevelError as https_error:
        LAST_RETRIEVAL_METHOD = "Retrieval failed"

        raise RiverLevelError(
            f"{RIVER_PRODUCT} could not be retrieved. "
            f"FTP error: {ftp_error} "
            f"HTTPS error: {https_error}"
        ) from https_error


# =========================================================
# HTML parser
# =========================================================

def parse_river_levels(
    html: str,
) -> tuple[list[dict], str | None]:
    """
    Parse selected gauges from IDQ60286.html.
    """

    soup = BeautifulSoup(
        html,
        "lxml",
    )

    table = soup.select_one(
        "table.rhb"
    )

    if table is None:
        raise RiverLevelError(
            "Could not find the river-height table "
            f"in {RIVER_PRODUCT}."
        )

    headers = [
        clean(
            heading.get_text(
                " ",
                strip=True,
            )
        )
        for heading in table.select(
            "thead th"
        )
    ]

    expected_headers = [
        "Station Name",
        "Station Type",
        "Time/Day",
        "Height (m)",
        "Gauge Datum",
        "Tendency",
        "Crossing (m)",
        "Flood Classification",
        "Recent Data",
    ]

    if headers != expected_headers:
        raise RiverLevelError(
            "Unexpected river-height columns. "
            f"Found: {headers}"
        )

    page_text = clean(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    issued_match = ISSUED_RE.search(
        page_text
    )

    issued = (
        clean(issued_match.group(1))
        if issued_match
        else None
    )

    records = []
    catchment = None

    for table_row in table.select(
        "tbody tr"
    ):
        section = table_row.find(
            "th",
            class_="rowlevel1",
        )

        if section:
            catchment = clean(
                section.get_text(
                    " ",
                    strip=True,
                )
            )
            continue

        cells = table_row.find_all(
            "td",
            recursive=False,
        )

        if len(cells) != len(
            expected_headers
        ):
            continue

        values = [
            clean(
                cell.get_text(
                    " ",
                    strip=True,
                )
            )
            for cell in cells
        ]

        recent_data_links = " ".join(
            link.get("href", "")
            for link in cells[8].find_all(
                "a"
            )
        )

        gauge_match = GAUGE_RE.search(
            recent_data_links
        )

        gauge = (
            gauge_match.group(1)
            if gauge_match
            else None
        )

        target = TARGET_BY_GAUGE.get(
            gauge
        )

        if target is None:
            continue

        height_text = values[3]

        try:
            height = (
                float(height_text)
                if height_text
                else None
            )

        except ValueError:
            height = None

        tendency = (
            values[5].capitalize()
            if values[5]
            else None
        )

        records.append({
            "Gauge Number": gauge,
            "Location": target["location"],
            "Source Station": values[0],
            "Observation Time": (
                values[2] or None
            ),
            "Current River Level (m)": height,
            "Gauge Datum": (
                values[4] or None
            ),
            "Rising/Falling/Steady": tendency,
        })

    records_by_gauge = {
        record["Gauge Number"]: record
        for record in records
    }

    complete_records = []

    for target in TARGET_GAUGES:
        gauge = target["gauge"]

        if gauge in records_by_gauge:
            complete_records.append(
                records_by_gauge[gauge]
            )
            continue

        complete_records.append({
            "Gauge Number": gauge,
            "Location": target["location"],
            "Source Station": None,
            "Observation Time": None,
            "Current River Level (m)": None,
            "Gauge Datum": None,
            "Rising/Falling/Steady": None,
        })

    records = complete_records

    return records, issued


# =========================================================
# Public collection function used by Streamlit
# =========================================================

def collect_river_levels():
    """
    Retrieve and parse the latest river-level bulletin.

    No uploaded HTML argument is required.
    """

    html = fetch_river_html()

    records, issued = parse_river_levels(
        html
    )

    source = (
        LAST_RETRIEVAL_METHOD
        or f"BoM {RIVER_PRODUCT}"
    )

    return records, issued, source


# =========================================================
# Optional FTP diagnostic
# =========================================================

def test_river_ftp_connection():
    """
    Test whether the Streamlit server can access the river
    product through BoM anonymous FTP.
    """

    result = {
        "host": FTP_HOST,
        "directory": FTP_DIRECTORY,
        "filename": RIVER_FILENAME,
        "connected": False,
        "found": False,
        "size_bytes": None,
    }

    try:
        with FTP(
            host=FTP_HOST,
            timeout=FTP_TIMEOUT,
        ) as ftp:
            ftp.login()
            ftp.set_pasv(True)
            ftp.cwd(FTP_DIRECTORY)

            result["connected"] = True

            matching_files = ftp.nlst(
                f"{RIVER_PRODUCT}*"
            )

            result["found"] = (
                RIVER_FILENAME
                in matching_files
            )

            if result["found"]:
                try:
                    result["size_bytes"] = (
                        ftp.size(
                            RIVER_FILENAME
                        )
                    )

                except all_errors:
                    result["size_bytes"] = None

    except all_errors as exc:
        raise RiverLevelError(
            f"BoM river FTP test failed: {exc}"
        ) from exc

    return result
