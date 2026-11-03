#!/usr/bin/env python3
"""
BoM rainfall tracker for a handful of gauges.

Fetches the 1-hour, 3-hour and 24-hour rainfall bulletins for Brisbane / Pine /
Caboolture rivers, pulls out only the stations listed in STATIONS below, then:

  * prints three small tables (1h, 3h, 24h + "since 9am"),
  * writes the latest snapshot to rainfall_latest.json,
  * upserts every reading into rainfall_log.csv (builds a history longer than the
    24 h / 7 day windows the bulletins show).

Usage
-----
    python bom_rainfall_app.py                    # run once
    python bom_rainfall_app.py --watch 60         # re-run every 60 minutes
    python bom_rainfall_app.py --json             # print JSON instead of tables
    python bom_rainfall_app.py --html-dir pages/  # use saved 1h.html / 3h.html / 24h.html

Requires: pip install requests beautifulsoup4 lxml
"""
import difflib
import re
import sys
import time

from datetime import datetime, timedelta, timezone
from pathlib import Path
from ftplib import FTP, all_errors
from io import BytesIO

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# CONFIG - edit this section
# --------------------------------------------------------------------------- #
LAST_RETRIEVAL_METHOD = {}
FTP_HOST = "ftp.bom.gov.au"
FTP_DIRECTORY = "/anon/gen/fwo"
FTP_TIMEOUT = 20
BASE_URL = "https://www.bom.gov.au/cgi-bin/wrap_fwo.pl?{product}.html"
BULLETINS = {
    "1h":  {"product": "IDQ60336", "hours": 1},
    "3h":  {"product": "IDQ60348", "hours": 3},
    "24h": {"product": "IDQ60360", "hours": 24},
}

# The bulletins do NOT show station numbers, only names, so each station is matched
# by the exact name used in the bulletin ("bom_names"). If several names are listed,
# the one that actually has data wins. Names were matched to your IDs using BoM's
# Queensland flood-warning gauge index - please sanity-check the notes below.
STATIONS = [
    {
        "id": "040793",
        "label": "Lyons",
        "bom_names": ["Lyons"],
    },
    {
        "id": "540250",
        "label": "Ipswich",
        "bom_names": ["Brassall (Hancocks Bridge)"],
    },
    {
        "id": "540387",
        "label": "Warrill View",
        "bom_names": ["Harrisville"],
    },
    {
        "id": "540503",
        "label": "Rosewood",
        "bom_names": ["Rosewood Detention Basin"],
    },
    {
        "id": "540574",
        "label": "Mount Walker",
        "bom_names": ["Lower Mt Walker"],
    },
    {
        "id": "040135",
        "label": "Moogerah",
        "bom_names": ["Moogerah Dam HG"],
    },
]

MIN_WATCH_MINUTES = 15   # be polite to BoM; the bulletins only update about hourly
# --------------------------------------------------------------------------- #

AEST = timezone(timedelta(hours=10))  # Queensland has no daylight saving
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-AU,en;q=0.9",
}
TIME_LABEL = re.compile(r"^\d{1,2}\s*[AP]M$", re.I)      # 4AM, 12PM
DAY_LABEL = re.compile(r"^\d{1,2}$")                      # 27, 01
ISSUED = re.compile(r"Issued at\s+(\d{1,2}:\d{2}\s*[AP]M)\s+\w+\s+\w+\s+(\d{1,2}\s+\w+\s+\d{4})", re.I)
SINCE_9AM = re.compile(r"Since\s*9am\s+(\d{1,2})\s+([A-Za-z]{3})", re.I)

LOG_FIELDS = ["series", "station_id", "station", "bom_station",
              "period_start", "period_end", "rainfall_mm", "issued"]


class BulletinError(Exception):
    pass


def warn(msg):
    print(f"Warning: {msg}", file=sys.stderr)


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def norm(name):
    return clean(name).casefold()


# ----------------------------- fetching ------------------------------------ #
def validate_rainfall_html(
    html,
    product,
    source,
):
    """
    Confirm that the retrieved content contains BoM rainfall tables.
    """

    if not html or not html.strip():
        raise BulletinError(
            f"{source} returned an empty file for {product}."
        )

    soup = BeautifulSoup(
        html,
        "lxml",
    )

    if not soup.select("table.rhb"):
        raise BulletinError(
            f"{source} did not contain the expected "
            f"rainfall tables for {product}."
        )

    return html


def fetch_html_from_ftp(product):
    """
    Retrieve the latest BoM FWO product using anonymous FTP.
    """

    filename = f"{product}.html"
    buffer = BytesIO()

    try:
        with FTP(
            host=FTP_HOST,
            timeout=FTP_TIMEOUT,
        ) as ftp:
            ftp.login()
            ftp.set_pasv(True)
            ftp.cwd(FTP_DIRECTORY)

            ftp.retrbinary(
                f"RETR {filename}",
                buffer.write,
            )

    except all_errors as exc:
        raise BulletinError(
            f"FTP retrieval failed for {filename}: {exc}"
        ) from exc

    raw = buffer.getvalue()

    if not raw:
        raise BulletinError(
            f"FTP returned an empty file for {filename}."
        )

    try:
        html = raw.decode("utf-8-sig")

    except UnicodeDecodeError:
        html = raw.decode(
            "windows-1252",
            errors="replace",
        )

    return validate_rainfall_html(
        html=html,
        product=product,
        source=f"FTP file {filename}",
    )


def fetch_html_from_https(product):
    """
    Retrieve the BoM product through HTTPS.

    This function is used only when FTP is unavailable.
    """

    url = BASE_URL.format(
        product=product,
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30,
        )

    except requests.RequestException as exc:
        raise BulletinError(
            f"HTTPS request failed for {product}: {exc}"
        ) from exc

    if response.status_code == 403:
        raise BulletinError(
            f"BoM blocked the HTTPS request for "
            f"{product} with HTTP 403."
        )

    try:
        response.raise_for_status()

    except requests.RequestException as exc:
        raise BulletinError(
            f"HTTPS request failed for {product}: {exc}"
        ) from exc

    return validate_rainfall_html(
        html=response.text,
        product=product,
        source="BoM HTTPS response",
    )

def fetch_html(product):
    """
    Retrieve the latest BoM rainfall product.

    Retrieval order:
    1. BoM anonymous FTP
    2. BoM HTTPS fallback
    """

    ftp_error = None

    try:
        html = fetch_html_from_ftp(
            product
        )

        LAST_RETRIEVAL_METHOD[product] = (
            f"BoM FTP {product}.html"
        )

        return html

    except BulletinError as exc:
        ftp_error = str(exc)

        warn(
            f"{product}: FTP unavailable. "
            f"Trying HTTPS. Details: {ftp_error}"
        )

    try:
        html = fetch_html_from_https(
            product
        )

        LAST_RETRIEVAL_METHOD[product] = (
            f"BoM HTTPS fallback {product}"
        )

        return html

    except BulletinError as https_error:
        LAST_RETRIEVAL_METHOD[product] = (
            "Retrieval failed"
        )

        raise BulletinError(
            f"{product}: both retrieval methods failed. "
            f"FTP error: {ftp_error}. "
            f"HTTPS error: {https_error}"
        ) from https_error
     
# ---Temporary FTP TEST---

def test_ftp_connection():
    """
    Test access to BoM anonymous FTP and list the rainfall products.
    """

    required_products = [
        "IDQ60336.html",
        "IDQ60348.html",
        "IDQ60360.html",
    ]

    result = {
        "host": FTP_HOST,
        "directory": FTP_DIRECTORY,
        "connected": False,
        "files": [],
        "missing": [],
    }

    with FTP(
        host=FTP_HOST,
        timeout=FTP_TIMEOUT,
    ) as ftp:
        ftp.login()
        ftp.cwd(FTP_DIRECTORY)
        ftp.set_pasv(True)

        available_files = set(ftp.nlst())

    result["connected"] = True

    result["files"] = [
        filename
        for filename in required_products
        if filename in available_files
    ]

    result["missing"] = [
        filename
        for filename in required_products
        if filename not in available_files
    ]

    return result

# ----------------------------- parsing ------------------------------------- #
def parse_issued(soup):
    m = ISSUED.search(soup.get_text(" ", strip=True))
    if not m:
        raise BulletinError("could not find the 'Issued at ...' line; page layout may have changed")
    t = re.sub(r"\s+", "", m.group(1).upper())
    d = clean(m.group(2))
    return datetime.strptime(f"{d} {t}", "%d %B %Y %I:%M%p").replace(tzinfo=AEST)


def hourly_columns(labels, issued, step, series):
    """Labels like ['12PM','3PM',...] -> period start/end for each column."""
    hours = [datetime.strptime(re.sub(r"\s+", "", l.upper()), "%I%p").hour for l in labels]
    last = issued.replace(hour=hours[-1], minute=0, second=0, microsecond=0)
    if last > issued:
        last -= timedelta(days=1)
    cols = []
    for i, h in enumerate(hours):
        end = last - timedelta(hours=step * (len(hours) - 1 - i))
        if end.hour != h:
            warn(f"{series}: column {labels[i]} doesn't line up with a {step}-hour step")
        cols.append({"series": series, "start": end - timedelta(hours=step), "end": end})
    return cols


def daily_columns(labels, issued, header_text):
    """Day-of-month labels (24 h to 9am) plus the trailing 'Since 9am' column."""
    m = SINCE_9AM.search(header_text)
    if not m:
        raise BulletinError("24h bulletin: could not find the 'Since 9am <date>' header")
    anchor = datetime.strptime(f"{int(m.group(1))} {m.group(2).title()} {issued.year} 09:00",
                               "%d %b %Y %H:%M").replace(tzinfo=AEST)
    if anchor > issued:                       # New Year edge case
        anchor = anchor.replace(year=issued.year - 1)
    cols = []
    for i, lab in enumerate(labels):
        end = anchor - timedelta(days=len(labels) - 1 - i)
        if end.day != int(lab):
            warn(f"24h: column '{lab}' doesn't match expected date {end:%d %b}")
        cols.append({"series": "24h", "start": end - timedelta(hours=24), "end": end})
    cols.append({"series": "since_9am", "start": anchor, "end": issued})
    return cols


def to_float(text):
    text = text.strip()
    if not text:
        return None            # blank = no recent observation, NOT zero rain
    try:
        return float(text)
    except ValueError:
        return None


def parse_bulletin(html, key):
    soup = BeautifulSoup(html, "lxml")
    tables = soup.select("table.rhb")
    if not tables:
        raise BulletinError(f"{key}: no rainfall tables found (got an error or bot-check page?)")
    issued = parse_issued(soup)
    step = BULLETINS[key]["hours"]

    rows = []
    for table in tables:
        columns, catchment, header_text = None, None, ""
        # The 24-hour date labels and "Since 9am" label may occupy separate
        # header rows. Read all table headers first so their order cannot break parsing.
        full_table_header = " ".join(clean(th.get_text(" ", strip=True))
                                     for th in table.find_all("th"))
        for tr in table.find_all("tr"):
            ths = tr.find_all("th", recursive=False)
            tds = tr.find_all("td", recursive=False)
            if ths and not tds:
                labels = [clean(th.get_text(" ", strip=True)) for th in ths]
                header_text += " " + " ".join(labels)
                if all(TIME_LABEL.match(l) for l in labels):
                    columns = hourly_columns(labels, issued, step, key)
                elif all(DAY_LABEL.match(l) for l in labels):
                    columns = daily_columns(labels, issued, full_table_header)
                elif len(ths) == 1:
                    catchment = labels[0]
                continue
            if not tds or columns is None:
                continue
            cells = [clean(td.get_text(" ", strip=True)) for td in tds]
            name, values = cells[0], cells[1:]
            if len(values) != len(columns):
                warn(f"{key}: skipping '{name}' ({len(values)} values, expected {len(columns)})")
                continue
            rows.append({"catchment": catchment, "name": name, "columns": columns,
                         "values": [to_float(v) for v in values]})
    return issued, rows


# ----------------------------- selecting ----------------------------------- #
def pick_row(rows, bom_names):
    """Best row whose name exactly matches one of bom_names (most data wins)."""
    wanted = [norm(n) for n in bom_names]
    cands = [r for r in rows if norm(r["name"]) in wanted]
    if not cands:
        return None
    return max(cands, key=lambda r: (sum(v is not None for v in r["values"]),
                                     -wanted.index(norm(r["name"]))))


def station_records(rows, issued, key):
    out = []
    all_names = sorted({r["name"] for r in rows})
    for st in STATIONS:
        row = pick_row(rows, st["bom_names"])
        if row is None:
            close = difflib.get_close_matches(st["bom_names"][0], all_names, n=5, cutoff=0.5)
            warn(f"{key}: '{st['label']}' ({st['id']}) not found as {st['bom_names']}. "
                 f"Similar names in this bulletin: {close or 'none'}")
            continue
        for col, val in zip(row["columns"], row["values"]):
            out.append({
                "series": col["series"],
                "station_id": st["id"],
                "station": st["label"],
                "bom_station": row["name"],
                "catchment": row["catchment"],
                "period_start": col["start"].isoformat(),
                "period_end": col["end"].isoformat(),
                "rainfall_mm": val,
                "issued": issued.isoformat(),
            })
    return out


def collect(html_dir=None):
    records = []
    issued_by_bulletin = {}
    errors = []

    # Clear previous retrieval-method information before
    # performing a new live retrieval.
    if html_dir is None:
        LAST_RETRIEVAL_METHOD.clear()

    for i, (key, spec) in enumerate(
        BULLETINS.items()
    ):
        try:
            if html_dir:
                html = Path(
                    html_dir,
                    f"{key}.html",
                ).read_text(
                    encoding="utf-8"
                )

                LAST_RETRIEVAL_METHOD[
                    spec["product"]
                ] = "Local saved HTML"

            else:
                if i:
                    time.sleep(1.5)

                html = fetch_html(
                    spec["product"]
                )

            issued, rows = parse_bulletin(
                html,
                key,
            )

            issued_by_bulletin[key] = (
                issued.isoformat()
            )

            records += station_records(
                rows,
                issued,
                key,
            )

        except (
            BulletinError,
            OSError,
        ) as exc:
            errors.append(
                f"{key}: {exc}"
            )

            warn(
                f"{key}: {exc}"
            )

    return (
        records,
        issued_by_bulletin,
        errors,
    )

def get_retrieval_source():
    """
    Return a user-facing summary of the retrieval methods
    used for the current rainfall products.
    """

    expected_products = [
        specification["product"]
        for specification in BULLETINS.values()
    ]

    methods = [
        LAST_RETRIEVAL_METHOD.get(product)
        for product in expected_products
    ]

    if any(
        method == "Retrieval failed"
        for method in methods
    ):
        return "Partial rainfall retrieval"

    if any(
        method is None
        for method in methods
    ):
        return "Partial rainfall retrieval"

    if all(
        method.startswith("BoM FTP")
        for method in methods
    ):
        return "BoM anonymous FTP"

    if all(
        method.startswith("BoM HTTPS")
        for method in methods
    ):
        return "BoM HTTPS HTML fallback"

    if all(
        method == "Local saved HTML"
        for method in methods
    ):
        return "Local saved BoM HTML"

    if (
        any(
            method.startswith("BoM FTP")
            for method in methods
        )
        and any(
            method.startswith("BoM HTTPS")
            for method in methods
        )
    ):
        return (
            "Mixed: BoM anonymous FTP and "
            "HTTPS fallback"
        )

    return "Mixed rainfall retrieval sources"
