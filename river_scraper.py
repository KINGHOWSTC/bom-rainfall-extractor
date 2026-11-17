from datetime import datetime, timedelta

import pandas as pd
import requests
from bs4 import BeautifulSoup


# ------------------------------------------------------------------
# BoM river gauge station IDs
# ------------------------------------------------------------------

RIVER_GAUGES = {
    "Peak Crossing": "540065",
    "Loamside": "540062",
    "Kalbar Weir": "540057",
    "Harrisville": "540387",
    "Amberley": "540180",
    "Adams Bridge": "540157",
    "Rosewood": "540388",
    "Five Mile Bridge": "540147",
    "Walloon": "540504",
    "Three Mile Bridge": "040838",
    "Berrys Lagoon": "540216",
    "One Mile Bridge": "040836",
    "Brassall": "540250",
    "Ipswich": "040831",
}


BOM_TABLE_URL = (
    "https://www.bom.gov.au/fwo/IDQ65389/"
    "IDQ65389.{station_id}.tbl.shtml"
)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-AU,en;q=0.9",
}


# ------------------------------------------------------------------
# Parse one potential BoM observation row
# ------------------------------------------------------------------

def parse_observation_values(values):
    """
    Extract one timestamp and one river level from a table row.

    This does not assume whether the timestamp or level appears
    first in the HTML table.
    """

    timestamp = None
    level = None

    for value in values:
        text = str(value).strip()

        if timestamp is None:
            try:
                timestamp = datetime.strptime(
                    text,
                    "%d/%m/%Y %H:%M",
                )
                continue

            except ValueError:
                pass

        if level is None:
            try:
                level = float(text)

            except ValueError:
                pass

    if timestamp is None or level is None:
        return None

    return {
        "datetime": timestamp,
        "level": level,
    }


# ------------------------------------------------------------------
# Scrape a gauge page
# ------------------------------------------------------------------

def get_bom_river_table(station_id):
    """
    Retrieve and parse the BoM historical river table for one gauge.
    """

    station_id = str(
        station_id
    ).strip().zfill(6)

    url = BOM_TABLE_URL.format(
        station_id=station_id
    )

    response = requests.get(
        url,
        timeout=30,
        headers=REQUEST_HEADERS,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "lxml",
    )

    parsed_rows = []

    # Parse actual table rows only. This avoids processing the
    # page header, navigation menus, footer and unrelated text.
    for table_row in soup.select(
        "table tr"
    ):
        values = [
            cell.get_text(
                " ",
                strip=True,
            )
            for cell in table_row.find_all(
                [
                    "td",
                    "th",
                ],
                recursive=False,
            )
        ]

        if len(values) < 2:
            continue

        observation = parse_observation_values(
            values
        )

        if observation is None:
            continue

        parsed_rows.append(
            observation
        )

    if not parsed_rows:
        print(
            f"{station_id}: no valid river observations parsed"
        )

        return pd.DataFrame(
            columns=[
                "datetime",
                "level",
            ]
        )

    dataframe = pd.DataFrame(
        parsed_rows
    )

    dataframe = (
        dataframe
        .drop_duplicates(
            subset=["datetime"],
            keep="last",
        )
        .sort_values("datetime")
        .reset_index(drop=True)
    )

    print(
        f"{station_id}: "
        f"{len(dataframe)} valid observations parsed"
    )

    return dataframe


# ------------------------------------------------------------------
# Calculate 24-hour maximum
# ------------------------------------------------------------------

def get_24h_max(station_id):
    """
    Return the maximum river level in the latest 24-hour period.

    The 24-hour period is measured back from the newest observation,
    rather than the app server's current time. This avoids problems
    when BoM is delayed or the server clock differs slightly.
    """

    dataframe = get_bom_river_table(
        station_id
    )

    if dataframe.empty:
        return None

    latest_observation = dataframe[
        "datetime"
    ].max()

    cutoff = (
        latest_observation
        - timedelta(hours=24)
    )

    recent = dataframe[
        dataframe["datetime"] >= cutoff
    ]

    if recent.empty:
        return None

    maximum = pd.to_numeric(
        recent["level"],
        errors="coerce",
    ).max()

    if pd.isna(maximum):
        return None

    return float(
        maximum
    )


# ------------------------------------------------------------------
# Get all gauges
# ------------------------------------------------------------------

def get_all_24h_maxima():
    """
    Return one 24-hour maximum for every configured river gauge.
    """

    results = {}

    for gauge_name, station_id in (
        RIVER_GAUGES.items()
    ):
        try:
            results[gauge_name] = get_24h_max(
                station_id
            )

        except Exception as exc:
            print(
                f"{station_id} ({gauge_name}): "
                f"24-hour maximum retrieval failed: {exc}"
            )

            results[gauge_name] = None

    return results
