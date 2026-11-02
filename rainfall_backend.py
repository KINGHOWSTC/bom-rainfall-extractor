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

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# CONFIG - edit this section
# --------------------------------------------------------------------------- #
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
    # 540681 - ID not verified against the index; the bulletins carry "Moogerah Dam HG"
    #          (data) and "Moogerah Dam" (blank in the 24h bulletin).
    {"id": "540681", "label": "Moogerah",     "bom_names": ["Moogerah Dam HG", "Moogerah Dam"]},
    # 540387 is "HARRISVILLE AL-B" in BoM's index, shown as "Harrisville" in the bulletins.
    {"id": "540387", "label": "Warrill View", "bom_names": ["Harrisville"]},
    # 540574 is "LOWER MT WALKER ALERT".
    {"id": "540574", "label": "Mount Walker", "bom_names": ["Lower Mt Walker"]},
    # 540503 - ID not verified; matched on the plain name "Rosewood" (not the
    #          "Rosewood Detention Basin" / "Rosewood WWTP" gauges).
    {"id": "540503", "label": "Rosewood",     "bom_names": ["Rosewood"]},
    # 040793 is "LYONS ALERT" (your "40793" has lost its leading zero).
    {"id": "040793", "label": "Lyons",        "bom_names": ["Lyons"]},
    # 540250 is "BRASSALL(HANCOCKS BR) AL" in BoM's index. The bulletins ALSO have a
    # separate gauge literally called "Ipswich" - swap the name below if you want that one.
    {"id": "540250", "label": "Ipswich",      "bom_names": ["Brassall (Hancocks Bridge)"]},
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
def fetch_html(product):
    url = BASE_URL.format(product=product)
    last = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 403:
                raise BulletinError(
                    f"{product}: HTTP 403 - BoM's bot protection blocked the request. Save the page from your "
                    "browser and use --html-dir, or fetch it with a headless browser.")
            resp.raise_for_status()
            return resp.text
        except BulletinError:
            raise
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise BulletinError(f"{product}: could not fetch ({type(last).__name__}: {str(last)[:120]})")


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
    records, issued_by_bulletin, errors = [], {}, []
    for i, (key, spec) in enumerate(BULLETINS.items()):
        try:
            if html_dir:
                html = Path(html_dir, f"{key}.html").read_text(encoding="utf-8")
            else:
                if i:
                    time.sleep(1.5)
                html = fetch_html(spec["product"])
            issued, rows = parse_bulletin(html, key)
            issued_by_bulletin[key] = issued.isoformat()
            records += station_records(rows, issued, key)
        except (BulletinError, OSError) as exc:
            errors.append(f"{key}: {exc}")
            warn(f"{key}: {exc}")
    return records, issued_by_bulletin, errors


