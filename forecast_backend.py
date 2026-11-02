"""Elders Weather rain-amount forecast add-on.
Independent of rainfall_backend.py and river_level_backend.py.
"""
from __future__ import annotations
import re
import time
from datetime import date, datetime, timedelta
import requests
from bs4 import BeautifulSoup

FORECASTS = [
    {"station_number": "040135", "location": "Moogerah", "slug": "moogerah"},
    {"station_number": "540387", "location": "Warrill View", "slug": "warrill-view"},
    {"station_number": "540574", "location": "Mount Walker", "slug": "mount-walker"},
    {"station_number": "540503", "location": "Rosewood", "slug": "rosewood"},
    {"station_number": "040793", "location": "Lyons", "slug": "lyons"},
    {"station_number": "540250", "location": "Ipswich", "slug": "ipswich"},
]
BASE_URL = "https://eldersweather.com.au/forecast/qld/{slug}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-AU,en;q=0.9",
}
RAIN_RE = re.compile(r"^(?:\d+(?:\.\d+)?\s*(?:-|–|to)\s*)?\d+(?:\.\d+)?\s*mm$", re.I)
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

class ForecastError(RuntimeError):
    pass

def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()

def fetch_forecast_html(slug: str) -> str:
    url = BASE_URL.format(slug=slug)
    response = requests.get(url, headers=HEADERS, timeout=30)
    if response.status_code == 403:
        raise ForecastError("Elders Weather blocked the request (HTTP 403).")
    response.raise_for_status()
    if "Rain Amount" not in response.text:
        raise ForecastError("The page did not contain a Rain Amount forecast row.")
    return response.text

def _parse_header_date(text: str, today: date) -> date | None:
    text = clean(text)
    if text.casefold() == "today":
        return today
    match = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})", text)
    if not match:
        return None
    parsed = datetime.strptime(f"{match.group(1)} {match.group(2)} {today.year}", "%b %d %Y").date()
    # Resolve New Year: a January header seen in December belongs to next year,
    # while a December header seen in January belongs to the previous year.
    if parsed < today - timedelta(days=180):
        parsed = parsed.replace(year=today.year + 1)
    elif parsed > today + timedelta(days=180):
        parsed = parsed.replace(year=today.year - 1)
    return parsed

def _rain_range(value: str) -> tuple[float, float]:
    """Convert a published amount such as '2 - 5 mm' or '4 mm' to bounds."""
    numbers = [float(x) for x in NUMBER_RE.findall(value)]
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    if len(numbers) == 2:
        return numbers[0], numbers[1]
    raise ForecastError(f"Could not interpret Rain Amount value '{value}'.")


def _format_mm(value: float) -> str:
    formatted = f"{value:.2f}".rstrip("0").rstrip(".")
    return formatted


def cumulative_rain_amount(amounts: list[str], final_offset: int) -> str:
    """Sum forecast ranges from Today (offset 0) through final_offset inclusive."""
    required = amounts[:final_offset + 1]
    if len(required) != final_offset + 1 or any(not value for value in required):
        raise ForecastError(
            f"Cannot calculate cumulative forecast through day {final_offset}: "
            "one or more daily Rain Amount values are missing."
        )
    bounds = [_rain_range(value) for value in required]
    low = sum(item[0] for item in bounds)
    high = sum(item[1] for item in bounds)
    if low == high:
        return f"{_format_mm(low)} mm"
    return f"{_format_mm(low)} - {_format_mm(high)} mm"


def parse_forecast(html: str, expected_location: str, today: date | None = None) -> dict:
    today = today or date.today()
    soup = BeautifulSoup(html, "lxml")
    target_row = None
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if cells and clean(cells[0].get_text(" ", strip=True)).casefold() == "rain amount":
            target_row = tr
            break
    if target_row is None:
        raise ForecastError(f"{expected_location}: Rain Amount row not found.")

    rain_cells = target_row.find_all(["th", "td"], recursive=False)[1:]
    amounts = [clean(cell.get_text(" ", strip=True)) for cell in rain_cells]
    if len(amounts) < 6:
        raise ForecastError(f"{expected_location}: expected at least 6 forecast values, found {len(amounts)}.")
    for value in amounts:
        if value and not RAIN_RE.match(value):
            raise ForecastError(f"{expected_location}: unexpected Rain Amount value '{value}'.")

    table = target_row.find_parent("table")
    headers = []
    if table:
        first_row = table.find("tr")
        if first_row:
            headers = [clean(c.get_text(" ", strip=True)) for c in
                       first_row.find_all(["th", "td"], recursive=False)][1:]
    header_dates = [_parse_header_date(x, today) for x in headers]
    if len(header_dates) >= 6 and header_dates[0] == today:
        for offset in (1, 3, 5):
            expected = today + timedelta(days=offset)
            if header_dates[offset] != expected:
                raise ForecastError(
                    f"{expected_location}: forecast date at offset {offset} was "
                    f"{header_dates[offset]}, expected {expected}."
                )

    return {
        # User-defined cumulative windows, inclusive of Today:
        # 1 day = Today + Tomorrow (offsets 0..1)
        # 3 day = Today through Today + 3 (offsets 0..3)
        # 5 day = Today through Today + 5 (offsets 0..5)
        "1 Day Forecast": cumulative_rain_amount(amounts, 1),
        "3 Day Forecast": cumulative_rain_amount(amounts, 3),
        "5 Day Forecast": cumulative_rain_amount(amounts, 5),
    }

def collect_forecasts(html_by_slug: dict[str, str] | None = None):
    rows, errors = [], []
    html_by_slug = html_by_slug or {}
    for index, item in enumerate(FORECASTS):
        try:
            if item["slug"] in html_by_slug:
                html = html_by_slug[item["slug"]]
            else:
                if index:
                    time.sleep(0.75)
                html = fetch_forecast_html(item["slug"])
            values = parse_forecast(html, item["location"])
            rows.append({
                "Station Number": item["station_number"],
                "Location": item["location"],
                **values,
            })
        except (ForecastError, requests.RequestException) as exc:
            errors.append(f"{item['location']}: {exc}")
            rows.append({
                "Station Number": item["station_number"],
                "Location": item["location"],
                "1 Day Forecast": None,
                "3 Day Forecast": None,
                "5 Day Forecast": None,
            })
    return rows, errors
