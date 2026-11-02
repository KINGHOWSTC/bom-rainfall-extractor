"""Independent river-level add-on for BoM product IDQ60286.
Does not import or modify the rainfall backend.
"""
from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

RIVER_PRODUCT = "IDQ60286"
RIVER_URL = "https://www.bom.gov.au/cgi-bin/wrap_fwo.pl?IDQ60286.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-AU,en;q=0.9",
}
GAUGE_RE = re.compile(r"IDQ65389\.(\d{6})\.(?:plt|tbl)\.shtml", re.I)
ISSUED_RE = re.compile(r"Issued at\s+(.+?)(?=\s{2,}|$)", re.I)

# Only these prescribed gauges are returned to Streamlit. Matching requires both
# the gauge number in the Recent Data link and the exact BoM station-row name.
TARGET_GAUGES = [
    {"gauge": "540388", "location": "Rosewood", "source": "Bremer River at Rosewood"},
    {"gauge": "540147", "location": "Five Mile Bridge", "source": "Bremer River at Five Mile Bridge"},
    {"gauge": "540057", "location": "Kalbar", "source": "Warrill Creek at Kalbar Weir TW"},
    {"gauge": "540504", "location": "Walloon", "source": "Bremer River at Walloon"},
    {"gauge": "040831", "location": "Ipswich", "source": "Bremer River at Ipswich"},
]
TARGET_BY_GAUGE = {item["gauge"]: item for item in TARGET_GAUGES}

class RiverLevelError(RuntimeError):
    pass

def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()

def fetch_river_html() -> str:
    response = requests.get(RIVER_URL, headers=HEADERS, timeout=30)
    if response.status_code == 403:
        raise RiverLevelError("BoM blocked the automatic river-level request (HTTP 403).")
    response.raise_for_status()
    if RIVER_PRODUCT not in response.text:
        raise RiverLevelError("The response was not the expected IDQ60286 river-height bulletin.")
    return response.text

def parse_river_levels(html: str) -> tuple[list[dict], str | None]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.rhb")
    if table is None:
        raise RiverLevelError("Could not find the river-height table in IDQ60286.")

    headers = [clean(th.get_text(" ", strip=True)) for th in table.select("thead th")]
    expected = ["Station Name", "Station Type", "Time/Day", "Height (m)",
                "Gauge Datum", "Tendency", "Crossing (m)",
                "Flood Classification", "Recent Data"]
    if headers != expected:
        raise RiverLevelError(f"Unexpected river-height columns: {headers}")

    page_text = clean(soup.get_text(" ", strip=True))
    issued_match = re.search(
        r"Issued at\s+(\d{1,2}:\d{2}\s*(?:AM|PM)\s+(?:AEST|EST)\s+\w+\s+\d{1,2}\s+\w+\s+\d{4})",
        page_text, re.I,
    )
    issued = clean(issued_match.group(1)) if issued_match else None

    records = []
    catchment = None
    for tr in table.select("tbody tr"):
        section = tr.find("th", class_="rowlevel1")
        if section:
            catchment = clean(section.get_text(" ", strip=True))
            continue
        cells = tr.find_all("td", recursive=False)
        if len(cells) != len(expected):
            continue
        values = [clean(td.get_text(" ", strip=True)) for td in cells]
        links = " ".join(a.get("href", "") for a in cells[8].find_all("a"))
        gauge_match = GAUGE_RE.search(links)
        gauge = gauge_match.group(1) if gauge_match else None
        target = TARGET_BY_GAUGE.get(gauge)
        if target is None:
            continue
        if values[0] != target["source"]:
            raise RiverLevelError(
                f"Gauge {gauge} was found as '{values[0]}', expected '{target['source']}'."
            )
        height_text = values[3]
        try:
            height = float(height_text) if height_text else None
        except ValueError:
            height = None
        tendency = values[5].capitalize() if values[5] else None
        records.append({
            "Gauge Number": gauge,
            "Location": target["location"],
            "Source Station": values[0],
            "Observation Time": values[2] or None,
            "Current River Level (m)": height,
            "Gauge Datum": values[4] or None,
            "Rising/Falling/Steady": tendency,
        })
    found = {row["Gauge Number"] for row in records}
    missing = [item["gauge"] for item in TARGET_GAUGES if item["gauge"] not in found]
    if missing:
        raise RiverLevelError("Required river gauges were not found: " + ", ".join(missing))
    records.sort(key=lambda row: [x["gauge"] for x in TARGET_GAUGES].index(row["Gauge Number"]))
    return records, issued

def collect_river_levels(html: str | None = None):
    source = "Uploaded river-height HTML" if html is not None else "Live BoM IDQ60286"
    records, issued = parse_river_levels(html if html is not None else fetch_river_html())
    return records, issued, source
