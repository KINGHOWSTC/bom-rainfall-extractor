"""
BoM cumulative rainfall forecast backend.

Source:
    ftp.bom.gov.au/anon/gen/fwo/IDQ11295.xml

Mappings:
    Moogerah -> Boonah
    Warrill View -> Boonah
    Mount Walker -> Laidley
    Rosewood -> Ipswich
    Lyons -> Ipswich
    Ipswich -> Ipswich
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from ftplib import FTP, all_errors
from io import BytesIO
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo


FTP_HOST = "ftp.bom.gov.au"
FTP_DIRECTORY = "/anon/gen/fwo"
FTP_FILENAME = "IDQ11295.xml"
FTP_TIMEOUT = 30

BRISBANE_TZ = ZoneInfo("Australia/Brisbane")

CACHE_PATH = (
    Path(__file__).parent
    / "data"
    / "bom_forecast_cache.json"
)

FORECASTS = [
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
    for item in FORECASTS
}

NUMBER_RE = re.compile(
    r"\d+(?:\.\d+)?"
)

LAST_FORECAST_METADATA = {}


class ForecastError(RuntimeError):
    pass


def clean(value) -> str:
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value).replace("\xa0", " "),
    ).strip()


def tag_name(element) -> str:
    return element.tag.rsplit(
        "}",
        1,
    )[-1]


def first_element_text(
    root,
    requested_name,
):
    for element in root.iter():
        if tag_name(element) != requested_name:
            continue

        value = clean(element.text)

        if value:
            return value

    return None


def children_named(
    parent,
    requested_name,
):
    return [
        child
        for child in list(parent)
        if tag_name(child) == requested_name
    ]


def typed_child(
    parent,
    child_name,
    type_name,
):
    for child in children_named(
        parent,
        child_name,
    ):
        if child.get("type") == type_name:
            return child

    return None


def parse_range(value):
    text = clean(value)

    if not text:
        return None, None

    values = [
        float(number)
        for number in NUMBER_RE.findall(text)
    ]

    if len(values) == 1:
        return values[0], values[0]

    if len(values) == 2:
        return values[0], values[1]

    return None, None


def format_number(value):
    return (
        f"{float(value):.2f}"
        .rstrip("0")
        .rstrip(".")
    )


def format_range(minimum, maximum):
    if minimum == maximum:
        return f"{format_number(minimum)} mm"

    return (
        f"{format_number(minimum)} - "
        f"{format_number(maximum)} mm"
    )


def download_forecast_xml():
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
                f"RETR {FTP_FILENAME}",
                buffer.write,
            )

    except all_errors as exc:
        raise ForecastError(
            f"BoM FTP retrieval failed: {exc}"
        ) from exc

    content = buffer.getvalue()

    if not content:
        raise ForecastError(
            f"{FTP_FILENAME} was empty."
        )

    return content


def parse_forecast_xml(xml_bytes):
    try:
        root = ET.fromstring(xml_bytes)

    except ET.ParseError as exc:
        raise ForecastError(
            f"Invalid BoM forecast XML: {exc}"
        ) from exc

    issue_time = (
        first_element_text(
            root,
            "issue-time-local",
        )
        or first_element_text(
            root,
            "issue-time-utc",
        )
    )

    next_issue_time = (
        first_element_text(
            root,
            "next-routine-issue-time-local",
        )
        or first_element_text(
            root,
            "next-routine-issue-time-utc",
        )
    )

    if not issue_time:
        raise ForecastError(
            "BoM forecast issue time was not found."
        )

    locations = {}

    for area in root.iter():
        if tag_name(area) != "area":
            continue

        if area.get("type") != "location":
            continue

        aac = area.get("aac")

        if not aac:
            continue

        forecasts = {}

        for period in children_named(
            area,
            "forecast-period",
        ):
            period_start = (
                period.get("start-time-local")
                or period.get("start-time-utc")
            )

            if not period_start:
                continue

            forecast_date = period_start[:10]

            range_element = typed_child(
                period,
                "element",
                "precipitation_range",
            )

            range_text = (
                clean(range_element.text)
                if range_element is not None
                else ""
            )

            minimum, maximum = parse_range(
                range_text
            )

            forecasts[forecast_date] = {
                "min_mm": minimum,
                "max_mm": maximum,
                "range_text": range_text or None,
                "source_issue_time": issue_time,
            }

        locations[aac] = {
            "description": clean(
                area.get("description")
            ),
            "forecasts": forecasts,
        }

    missing = REQUIRED_AACS - set(locations)

    if missing:
        raise ForecastError(
            "Required BoM forecast locations missing: "
            + ", ".join(sorted(missing))
        )

    return {
        "product": "IDQ11295",
        "issue_time": issue_time,
        "next_issue_time": next_issue_time,
        "locations": locations,
    }


def load_cache():
    if not CACHE_PATH.exists():
        return None

    try:
        return json.loads(
            CACHE_PATH.read_text(
                encoding="utf-8",
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ):
        return None


def save_cache(package):
    CACHE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = CACHE_PATH.with_suffix(
        ".tmp"
    )

    temporary_path.write_text(
        json.dumps(
            package,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary_path.replace(CACHE_PATH)


def valid_range(record):
    return (
        record is not None
        and record.get("min_mm") is not None
        and record.get("max_mm") is not None
    )


def issue_datetime(package):
    value = package.get("issue_time")

    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )

    except ValueError:
        return None


def merge_packages(
    cached_package,
    new_package,
):
    if not cached_package:
        return deepcopy(new_package)

    cached_issue = issue_datetime(
        cached_package
    )
    new_issue = issue_datetime(
        new_package
    )

    if (
        cached_issue is not None
        and new_issue is not None
        and new_issue <= cached_issue
    ):
        return deepcopy(cached_package)

    merged = deepcopy(cached_package)

    merged["product"] = new_package[
        "product"
    ]
    merged["issue_time"] = new_package[
        "issue_time"
    ]
    merged["next_issue_time"] = (
        new_package["next_issue_time"]
    )

    for aac, new_location in (
        new_package["locations"].items()
    ):
        merged["locations"].setdefault(
            aac,
            {
                "description": new_location[
                    "description"
                ],
                "forecasts": {},
            },
        )

        merged_location = merged[
            "locations"
        ][aac]

        merged_location["description"] = (
            new_location["description"]
        )

        for forecast_date, new_record in (
            new_location["forecasts"].items()
        ):
            old_record = merged_location[
                "forecasts"
            ].get(forecast_date)

            if valid_range(new_record):
                merged_location[
                    "forecasts"
                ][forecast_date] = new_record

            elif valid_range(old_record):
                continue

            else:
                merged_location[
                    "forecasts"
                ][forecast_date] = new_record

    return merged


def cumulative_forecast(
    forecasts,
    today,
    final_offset,
):
    minimum_total = 0.0
    maximum_total = 0.0
    missing_dates = []

    for offset in range(
        final_offset + 1
    ):
        forecast_date = (
            today
            + timedelta(days=offset)
        )

        date_key = forecast_date.isoformat()

        record = forecasts.get(date_key)

        if not valid_range(record):
            missing_dates.append(date_key)
            continue

        minimum_total += record["min_mm"]
        maximum_total += record["max_mm"]

    if missing_dates:
        return None, missing_dates

    return (
        format_range(
            minimum_total,
            maximum_total,
        ),
        [],
    )


def collect_forecasts():
    global LAST_FORECAST_METADATA

    errors = []
    cached_package = load_cache()

    try:
        new_package = parse_forecast_xml(
            download_forecast_xml()
        )

        package = merge_packages(
            cached_package,
            new_package,
        )

        save_cache(package)

        source = "BoM anonymous FTP"

    except (
        ForecastError,
        OSError,
    ) as exc:
        if not cached_package:
            rows = [
                {
                    "Station Number": item[
                        "station_number"
                    ],
                    "Location": item["location"],
                    "1 Day Forecast": None,
                    "3 Day Forecast": None,
                    "5 Day Forecast": None,
                }
                for item in FORECASTS
            ]

            LAST_FORECAST_METADATA = {
                "product": "IDQ11295",
                "source": "Unavailable",
                "issue_time": None,
                "next_issue_time": None,
                "location_mapping": [
                    {
                        "Station Number": item[
                            "station_number"
                        ],
                        "Project Location": item[
                            "location"
                        ],
                        "BoM Forecast Location": item[
                            "bom_location"
                        ],
                        "BoM AAC": item[
                            "bom_aac"
                        ],
                    }
                    for item in FORECASTS
                ],
            }
            errors.append(str(exc))

            return rows, errors

        package = cached_package
        source = "Cached BoM forecast"

        errors.append(
            "Latest BoM forecast retrieval failed. "
            "Using the cached forecast. "
            f"Details: {exc}"
        )

    today = datetime.now(
        BRISBANE_TZ
    ).date()

    rows = []

    for item in FORECASTS:
        forecasts = package[
            "locations"
        ][item["bom_aac"]][
            "forecasts"
        ]

        one_day, missing_1 = (
            cumulative_forecast(
                forecasts,
                today,
                1,
            )
        )

        three_day, missing_3 = (
            cumulative_forecast(
                forecasts,
                today,
                3,
            )
        )

        five_day, missing_5 = (
            cumulative_forecast(
                forecasts,
                today,
                5,
            )
        )

        for label, missing_dates in (
            ("1 Day Forecast", missing_1),
            ("3 Day Forecast", missing_3),
            ("5 Day Forecast", missing_5),
        ):
            if missing_dates:
                errors.append(
                    f"{item['location']}: "
                    f"{label} incomplete. Missing "
                    + ", ".join(missing_dates)
                )

        rows.append({
            "Station Number": item[
                "station_number"
            ],
            "Location": item["location"],
            "1 Day Forecast": one_day,
            "3 Day Forecast": three_day,
            "5 Day Forecast": five_day,
        })

    LAST_FORECAST_METADATA = {
        "product": package.get(
            "product",
            "IDQ11295",
        ),
        "source": source,
        "issue_time": package.get(
            "issue_time"
        ),
        "next_issue_time": package.get(
            "next_issue_time"
        ),
        "location_mapping": [
            {
                "Station Number": item[
                    "station_number"
                ],
                "Project Location": item[
                    "location"
                ],
                "BoM Forecast Location": item[
                    "bom_location"
                ],
                "BoM AAC": item[
                    "bom_aac"
                ],
            }
            for item in FORECASTS
        ],
    }

    return rows, errors


def get_forecast_metadata():
    return dict(LAST_FORECAST_METADATA)
