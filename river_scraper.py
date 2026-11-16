import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# ------------------------------------------------------------------
# BoM river gauge station IDs
# ------------------------------------------------------------------

RIVER_GAUGES = {
    "Loamside": "540062",
    "Kalbar Weir": "540057",
    "Harrisville": "540387",
    "Amberley": "540180",
    "Adams Bridge": "540157",
    "Rosewood": "540388",
    "Five Mile Bridge": "540147",
    "Walloon": "540504",
    "One Mile Bridge": "040836",
    "Brassall": "540250",
    "Ipswich": "040831",
}

# ------------------------------------------------------------------
# Scrape a gauge page
# ------------------------------------------------------------------

def get_bom_river_table(station_id):

    url = (
        f"https://www.bom.gov.au/fwo/IDQ65389/"
        f"IDQ65389.{station_id}.tbl.shtml"
    )

    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    text = soup.get_text("\n")

    rows = []

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for i in range(len(lines) - 1):

        try:

            timestamp = datetime.strptime(
                lines[i],
                "%d/%m/%Y %H:%M"
            )

            level = float(lines[i + 1])

            rows.append(
                {
                    "datetime": timestamp,
                    "level": level
                }
            )

        except Exception:
            continue

    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# Calculate 24h max
# ------------------------------------------------------------------

def get_24h_max(station_id):

    df = get_bom_river_table(station_id)

    if df.empty:
        return None

    cutoff = datetime.now() - timedelta(hours=24)

    recent = df[
        df["datetime"] >= cutoff
    ]

    if recent.empty:
        return None

    return float(recent["level"].max())


# ------------------------------------------------------------------
# Get all gauges
# ------------------------------------------------------------------

def get_all_24h_maxima():

    results = {}

    for gauge_name, station_id in RIVER_GAUGES.items():

        try:

            results[gauge_name] = get_24h_max(
                station_id
            )

        except Exception:

            results[gauge_name] = None

    return results
