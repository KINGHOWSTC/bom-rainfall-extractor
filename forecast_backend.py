"""
Elders Weather cumulative rainfall forecast scraper.

Cumulative periods:
- 1 Day Forecast = Today + Tomorrow
- 3 Day Forecast = Today through Today + 3 days
- 5 Day Forecast = Today through Today + 5 days
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


FORECASTS = [
    {
        "station_number": "040135",
        "location": "Moogerah",
        "slug": "moogerah",
    },
    {
        "station_number": "540387",
        "location": "Warrill View",
        "slug": "warrill-view",
    },
    {
        "station_number": "540574",
        "location": "Mount Walker",
        "slug": "mount-walker",
    },
    {
        "station_number": "540503",
        "location": "Rosewood",
        "slug": "rosewood",
    },
    {
        "station_number": "040793",
        "location": "Lyons",
        "slug": "lyons",
    },
    {
        "station_number": "540250",
        "location": "Ipswich",
        "slug": "ipswich",
    },
]


BASE_URL = "https://eldersweather.com.au/forecast/qld/{slug}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-AU,en;q=0.9",
}

RAIN_RE = re.compile(
    r"^(?:\d+(?:\.\d+)?\s*(?:-|–|to)\s*)?"
    r"\d+(?:\.\d+)?\s*mm$",
    re.IGNORECASE,
)

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


class ForecastError(RuntimeError):
    pass


def clean(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        value.replace("\xa0", " "),
    ).strip()


def fetch_forecast_html(slug: str) -> str:
    url = BASE_URL.format(slug=slug)

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    if response.status_code == 403:
        raise ForecastError(
            "Elders Weather blocked the request (HTTP 403)."
        )

    response.raise_for_status()

    if "Rain Amount" not in response.text:
        raise ForecastError(
            "The page did not contain a Rain Amount row."
        )

    return response.text


def parse_header_date(
    text: str,
    today: date,
) -> date | None:
    text = clean(text)

    if text.casefold() == "today":
        return today

    match = re.search(
        r"([A-Z][a-z]{2})\s+(\d{1,2})",
        text,
    )

    if not match:
        return None

    parsed = datetime.strptime(
        f"{match.group(1)} {match.group(2)} {today.year}",
        "%b %d %Y",
    ).date()

    # Allow forecast dates to cross from December into January.
    if parsed < today - timedelta(days=180):
        parsed = parsed.replace(year=today.year + 1)

    elif parsed > today + timedelta(days=180):
        parsed = parsed.replace(year=today.year - 1)

    return parsed


def rain_range(value: str) -> tuple[float, float]:
    """
    Convert a forecast such as:
        2 - 5 mm
        3 mm

    into lower and upper numerical bounds.
    """

    numbers = [
        float(number)
        for number in NUMBER_RE.findall(value)
    ]

    if len(numbers) == 1:
        return numbers[0], numbers[0]

    if len(numbers) == 2:
        return numbers[0], numbers[1]

    raise ForecastError(
        f"Could not interpret Rain Amount value '{value}'."
    )


def format_mm(value: float) -> str:
    """
    Display whole numbers without decimal places while preserving
    decimal values when required.
    """

    return f"{value:.2f}".rstrip("0").rstrip(".")


def cumulative_rain_amount(
    amounts: list[str],
    final_offset: int,
) -> str:
    """
    Sum daily forecast ranges from Today through final_offset.

    final_offset = 1:
        Today + Tomorrow

    final_offset = 3:
        Today + Tomorrow + Day 2 + Day 3

    final_offset = 5:
        Today through Day 5
    """

    required_amounts = amounts[: final_offset + 1]

    required_count = final_offset + 1

    if len(required_amounts) != required_count:
        raise ForecastError(
            f"Expected {required_count} daily values for the "
            f"cumulative forecast, but found "
            f"{len(required_amounts)}."
        )

    if any(not value for value in required_amounts):
        raise ForecastError(
            "One or more daily Rain Amount values are missing."
        )

    bounds = [
        rain_range(value)
        for value in required_amounts
    ]

    lower_total = sum(
        lower
        for lower, upper in bounds
    )

    upper_total = sum(
        upper
        for lower, upper in bounds
    )

    if lower_total == upper_total:
        return f"{format_mm(lower_total)} mm"

    return (
        f"{format_mm(lower_total)} - "
        f"{format_mm(upper_total)} mm"
    )


def parse_forecast(
    html: str,
    expected_location: str,
    today: date | None = None,
) -> dict:
    today = today or datetime.now(
        ZoneInfo("Australia/Brisbane")
    ).date()

    soup = BeautifulSoup(html, "lxml")

    rain_row = None

    for table_row in soup.find_all("tr"):
        cells = table_row.find_all(
            ["th", "td"],
            recursive=False,
        )

        if not cells:
            continue

        row_name = clean(
            cells[0].get_text(" ", strip=True)
        )

        if row_name.casefold() == "rain amount":
            rain_row = table_row
            break

    if rain_row is None:
        raise ForecastError(
            f"{expected_location}: Rain Amount row not found."
        )

    rain_cells = rain_row.find_all(
        ["th", "td"],
        recursive=False,
    )[1:]

    amounts = [
        clean(cell.get_text(" ", strip=True))
        for cell in rain_cells
    ]

    # Today through Day 5 requires six daily forecast values.
    if len(amounts) < 6:
        raise ForecastError(
            f"{expected_location}: expected at least 6 "
            f"daily Rain Amount values, but found "
            f"{len(amounts)}."
        )

    for amount in amounts:
        if amount and not RAIN_RE.match(amount):
            raise ForecastError(
                f"{expected_location}: unexpected "
                f"Rain Amount value '{amount}'."
            )

    # Validate forecast date ordering when suitable headers exist.
    table = rain_row.find_parent("table")
    header_labels = []

    if table:
        first_row = table.find("tr")

        if first_row:
            header_labels = [
                clean(cell.get_text(" ", strip=True))
                for cell in first_row.find_all(
                    ["th", "td"],
                    recursive=False,
                )[1:]
            ]

    header_dates = [
        parse_header_date(label, today)
        for label in header_labels
    ]

    if (
        len(header_dates) >= 6
        and header_dates[0] == today
    ):
        for offset in range(6):
            expected_date = today + timedelta(days=offset)

            if header_dates[offset] != expected_date:
                raise ForecastError(
                    f"{expected_location}: forecast column "
                    f"{offset} was dated "
                    f"{header_dates[offset]}, expected "
                    f"{expected_date}."
                )

    return {
        # Today + Tomorrow
        "1 Day Forecast": cumulative_rain_amount(
            amounts,
            final_offset=1,
        ),

        # Today + Tomorrow + Day 2 + Day 3
        "3 Day Forecast": cumulative_rain_amount(
            amounts,
            final_offset=3,
        ),

        # Today through Day 5
        "5 Day Forecast": cumulative_rain_amount(
            amounts,
            final_offset=5,
        ),
    }


def collect_forecasts(
    html_by_slug: dict[str, str] | None = None,
):
    rows = []
    errors = []

    html_by_slug = html_by_slug or {}

    for index, item in enumerate(FORECASTS):
        try:
            if item["slug"] in html_by_slug:
                html = html_by_slug[item["slug"]]

            else:
                # Avoid sending all requests at exactly the same time.
                if index:
                    time.sleep(0.75)

                html = fetch_forecast_html(
                    item["slug"]
                )

            forecast_values = parse_forecast(
                html,
                item["location"],
            )

            rows.append({
                "Station Number": item["station_number"],
                "Location": item["location"],
                **forecast_values,
            })

        except (
            ForecastError,
            requests.RequestException,
        ) as exc:
            errors.append(
                f"{item['location']}: {exc}"
            )

            rows.append({
                "Station Number": item["station_number"],
                "Location": item["location"],
                "1 Day Forecast": None,
                "3 Day Forecast": None,
                "5 Day Forecast": None,
            })

    return rows, errors
