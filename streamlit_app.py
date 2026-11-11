"""Streamlit front end for selected BoM rainfall gauges."""

from datetime import datetime
from io import BytesIO
from pathlib import Path
import json

import pandas as pd
import streamlit as st
from openpyxl import load_workbook

import rainfall_backend as rb
import river_level_backend as river
import forecast_backend as forecast

st.set_page_config(page_title="Rainfall Data Extractor", page_icon="🌧️", layout="wide")

SERIES_LABELS = {
    "1h": "1-hour rainfall",
    "3h": "3-hour rainfall",
    "24h": "24-hour rainfall to 9 am",
    "since_9am": "Rainfall since 9 am",
}
STATION_ORDER = [s["label"] for s in rb.STATIONS]

def dataframe(records):
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["period_start"] = pd.to_datetime(df["period_start"])
    df["period_end"] = pd.to_datetime(df["period_end"])
    df["issued"] = pd.to_datetime(df["issued"])
    df["rainfall_mm"] = pd.to_numeric(df["rainfall_mm"], errors="coerce")
    df["period"] = df["series"].map(SERIES_LABELS).fillna(df["series"])
    df["station"] = pd.Categorical(df["station"], STATION_ORDER, ordered=True)
    return df.sort_values(["station", "series", "period_end"])

def rainfall_daily_mode(df):
    """
    Return 'completed' only when the BoM bulletin contains a
    completed 24-hour period ending at today's 9 am AEST.

    Otherwise, return 'current' and use the Since 9 am value.
    """

    if df.empty:
        return "current"

    now_aest = datetime.now(
        rb.AEST
    )

    today_9am = now_aest.replace(
        hour=9,
        minute=0,
        second=0,
        microsecond=0,
    )

    daily_periods = df[
        df["series"] == "24h"
    ]

    if daily_periods.empty:
        return "current"

    latest_daily_end = pd.to_datetime(
        daily_periods["period_end"],
        errors="coerce",
    ).dropna()

    if latest_daily_end.empty:
        return "current"

    latest_daily_end = latest_daily_end.max()

    if latest_daily_end.tzinfo is None:
        latest_daily_end = (
            latest_daily_end.tz_localize(
                rb.AEST
            )
        )
    else:
        latest_daily_end = (
            latest_daily_end.tz_convert(
                rb.AEST
            )
        )

    if latest_daily_end >= today_9am:
        return "completed"

    return "current"


def rainfall_daily_warning(df):
    """
    Return a warning after 9:30 am if the new completed
    24-hour rainfall period has not yet appeared.
    """

    now_aest = datetime.now(
        rb.AEST
    )

    update_threshold = now_aest.replace(
        hour=9,
        minute=30,
        second=0,
        microsecond=0,
    )

    if (
        now_aest >= update_threshold
        and rainfall_daily_mode(df) != "completed"
    ):
        return (
            "The new 24-hour BoM rainfall period has not yet "
            "been detected. The table is still showing the "
            "current rainfall period since 9 am rather than "
            "labelling stale data as Past 24 hours."
        )

    return None

def hourly_periods_are_consecutive(
    group,
    required_hours,
):
    """
    Confirm that a group contains the required number of
    consecutive, non-overlapping one-hour periods.
    """

    if len(group) != required_hours:
        return False

    ordered = group.sort_values(
        "period_end"
    )

    starts = pd.to_datetime(
        ordered["period_start"]
    ).reset_index(drop=True)

    ends = pd.to_datetime(
        ordered["period_end"]
    ).reset_index(drop=True)

    for index in range(
        1,
        required_hours,
    ):
        if starts.iloc[index] != ends.iloc[
            index - 1
        ]:
            return False

    return True

def latest_table(df):
    if df.empty:
        return pd.DataFrame()

    location_order = [
        "Moogerah",
        "Warrill View",
        "Mount Walker",
        "Rosewood",
        "Lyons",
        "Ipswich",
    ]

    group_columns = [
        "station_id",
        "station",
    ]

    daily_mode = rainfall_daily_mode(
        df
    )

    # =====================================================
    # Hourly rainfall source
    # =====================================================

    hourly_data = (
        df[df["series"] == "1h"]
        .sort_values(
            [
                "station_id",
                "period_end",
            ]
        )
        .copy()
    )

    # =====================================================
    # Rolling 3-hour rainfall
    #
    # Missing hourly values are treated as zero for the sum,
    # but availability is counted and reported separately.
    # =====================================================

    latest_3_hour_rows = (
        hourly_data
        .groupby(
            group_columns,
            observed=True,
            group_keys=False,
        )
        .tail(3)
    )

    past_3_hours = (
        latest_3_hour_rows
        .groupby(
            group_columns,
            observed=True,
            as_index=False,
        )
        .agg(
            **{
                "Past **hours (mm)": (
                  **"rainfall_mm",
                  **lambda values: (
                **      values.fillna(0.0).sum()
  **                    if len(values**== 3
                        else**loat("nan")
                    )**                ),
              **"3-hour readings available": (
  **                "rainfall_mm",
  **                lambda values: in**
                        values.n**na().sum()
                    ),**               ),
               **3-hour slots found": (
          **        "rainfall_mm",
          **        "size",
                )**            }
        )
    )

  **# ===============================**====================
    # Rollin**6-hour rainfall
    #
    # Missi** hourly values are treated as zer**for the sum,
    # but availabili** is counted and reported separate**.
    # =========================**==========================

    l**est_6_hour_rows = (
        hourl**data
        .groupby(
          **group_columns,
            observ**=True,
            group_keys=Fal**,
        )
        .tail(6)
    **
    past_6_hours = (
        lat**t_6_hour_rows
        .groupby(
 **         group_columns,
         ** observed=True,
            as_in**x=False,
        )
        .agg(
**          **{
                "Pa** 6 hours (mm)": (
               **   "rainfall_mm",
               **   lambda values: (
             **         values.fillna(0.0).sum()**                       if len(val**s) == 6
                        e**e float("nan")
                  **),
                ),
           **   "6-hour readings available": (**                   "rainfall_mm",**                   lambda values:**nt(
                        value**notna().sum()
                   **,
                ),
            **  "6-hour slots found": (
       **           "rainfall_mm",
       **           "size",
              **),
            }
        )
    )
**   # ============================**=======================
    # Com**eted 24-hour rainfall periods
   ** ================================**===================

    daily_da** = (
        df[df["series"] == "24h"]
        .sort_values("period_**d")
        .copy()
    )

    la**st_completed_day = (
        dail**data
        .groupby(
          **group_columns,
            observ**=True,
            group_keys=Fal**,
        )
        .tail(1)[
            [
                "station_id",
                "station",
                "rainfall_mm",
            ]
        ]
        .rename(
**          columns={
             ** "rainfall_mm": (
               **   "_latest_completed_day"
      **        ),
            }
        **    )

    latest_two_completed_d**s = (
        daily_data
        **roupby(
            group_columns**            observed=True,
      **    group_keys=False,
        )
 **     .tail(2)
        .groupby(
 **         group_columns,
         ** observed=True,
            as_in**x=False,
        )
        .agg(
**          **{
                "_l**est_two_completed_days": (
      **            "rainfall_mm",
      **            lambda values: (
    **                  values.sum()
  **                    if (
        **                  len(values) == **                            and v**ues.notna().sum() == 2
          **            )
                   **   else float("nan")
            **      ),
                )
      **    }
        )
    )

    # ====**=================================**============
    # Current incomp**te rainfall period since 9 am
   ** ================================**===================

    since_9a**data = (
        df[df["series"] == "since_9am"]
        .sort_value**"period_end")
        .copy()
   **

    current_period = (
        **nce_9am_data
        .groupby(
  **        group_columns,
          **observed=True,
            group_**ys=False,
        )
        .tail**)[
            [
                "station_id",
                "station",
                "rainfall_mm",
            ]
        ]
        .**name(
            columns={
     **         "rainfall_mm": "_current**eriod",
            }
        )
 ** )

    # =======================**============================
    **Create one row for every configur** station
    # ==================**=================================**    table = pd.DataFrame(
       **
            {
                "station_id": station["id"],
                "station": station["label"],
            }
            for station in rb.STATIONS
        ]
    )**    table = (
        table
     ** .merge(
            past_3_hours**            on=group_columns,
   **       how="left",
        )
    **  .merge(
            past_6_hour**
            on=group_columns,
  **        how="left",
        )
   **   .merge(
            latest_com**eted_day,
            on=group_co**mns,
            how="left",
    **  )
        .merge(
            l**est_two_completed_days,
         ** on=group_columns,
            ho**"left",
        )
        .merge(**           current_period,
      **    on=group_columns,
           **ow="left",
        )
    )

    # =====================================================
    # Dynamic daily rainfall values
    # =====================================================

    if daily_mode == "completed":
        daily_column_name = (
            "Past 24 hours (mm)"
        )

        table[daily_column_name] = table[
            "_latest_completed_day"
        ]

        table["Past 2 days (mm)"] = table[
            "_latest_two_completed_days"
        ]

    else:
        daily_column_name = (
            "Current rainfall period (mm)"
        )

        table[daily_column_name] = table[
            "_current_period"
        ]

        table["Past 2 days (mm)"] = table.apply(
            lambda row: (
                row["_current_period"]
                + row["_latest_completed_day"]
                if (
                    pd.notna(
                        row["_current_period"]
                    )
                    and pd.notna(
                        row[
                            "_latest_completed_day"
                        ]
                    )
                )
                else float("nan")
            ),
            axis=1,
        )

    # =====================================================
    # Hourly availability warning
    # =====================================================

    def build_hourly_warning(row):
        warnings = []

        available_3 = int(
            row.get(
                "3-hour readings available",
                0,
            )
            or 0
        )

        slots_3 = int(
            row.get(
                "3-hour slots found",
                0,
            )
            or 0
        )

        available_6 = int(
            row.get(
                "6-hour readings available",
                0,
            )
            or 0
        )

        slots_6 = int(
            row.get(
                "6-hour slots found",
                0,
            )
            or 0
        )

        if (
            slots_3 < 3
            or available_3 < 3
        ):
            warnings.append(
                "Only "
                f"{available_3}/3 hourly readings "
                "available for the 3-hour total"
            )

        if (
            slots_6 < 6
            or available_6 < 6
        ):
            warnings.append(
                "Only "
                f"{available_6}/6 hourly readings "
                "available for the 6-hour total"
            )

        if not warnings:
            return ""

        return (
            "Warning: "
            + "; ".join(warnings)
            + ". Missing readings treated as 0."
        )

    table["Hourly data warning"] = table.apply(
        build_hourly_warning,
        axis=1,
    )

    table = table.drop(
        columns=[
            "_latest_completed_day",
            "_latest_two_completed_days",
            "_current_period",
            "3-hour readings available",
            "3-hour slots found",
            "6-hour readings available",
            "6-hour slots found",
        ],
        errors="ignore",
    )

    table["station"] = pd.Categorical(
        table["station"],
        categories=location_order,
        ordered=True,
    )

    table = (
        table
        .sort_values("station")
        .reset_index(drop=True)
    )

    return table.rename(
        columns={
            "station_id": "Station number",
            "station": "Location",
        }
    )
def rainfall_source_label():
    """
    Summarise which retrieval method supplied the rainfall products.
    """

    methods_by_product = getattr(
        rb,
        "LAST_RETRIEVAL_METHOD",
        {},
    )

    expected_products = [
        bulletin["product"]
        for bulletin in rb.BULLETINS.values()
    ]

    methods = [
        methods_by_product.get(product)
        for product in expected_products
    ]

    methods = [
        method
        for method in methods
        if method
    ]

    if not methods:
        return "BoM rainfall source unknown"

    if all(
        "FTP" in method
        for method in methods
    ):
        return "BoM anonymous FTP"

    if all(
        "HTTPS" in method
        for method in methods
    ):
        return "BoM HTTPS HTML fallback"

    if any(
        "FTP" in method
        for method in methods
    ) and any(
        "HTTPS" in method
        for method in methods
    ):
        return "Mixed: BoM FTP and HTTPS fallback"

    return "BoM rainfall retrieval"

def latest_bulletin_time(issued):
    """
    Return the most recent issue time among the rainfall bulletins.
    """

    if not issued:
        return None

    valid_times = []

    for value in issued.values():
        try:
            valid_times.append(
                pd.to_datetime(value)
            )
        except (
            ValueError,
            TypeError,
        ):
            continue

    if not valid_times:
        return None

    return max(valid_times)

def format_aest_datetime(value):
    """
    Format a datetime value as:
    DD-MM-YY HH:MM AEST
    """

    if value is None or str(value).strip() in {
        "",
        "Unknown",
        "None",
    }:
        return "Unknown"

    try:
        timestamp = pd.to_datetime(value)

        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(
                rb.AEST
            )
        else:
            timestamp = timestamp.tz_convert(
                rb.AEST
            )

        return timestamp.strftime(
            "%d-%m-%y %H:%M AEST"
        )

    except (
        ValueError,
        TypeError,
        AttributeError,
    ):
        return str(value)

def format_bom_issue_datetime(value):
    """
    Format a BoM bulletin issue string such as:
    03:08 PM AEST Tuesday 3 November 2026

    Output:
    03-11-26 15:08 AEST
    """

    if value is None or str(value).strip() in {
        "",
        "Unknown",
        "None",
    }:
        return "Unknown"

    text = str(value).strip()

    formats = [
        "%I:%M %p AEST %A %d %B %Y",
        "%I:%M %p EST %A %d %B %Y",
    ]

    for date_format in formats:
        try:
            timestamp = datetime.strptime(
                text,
                date_format,
            )

            return timestamp.strftime(
                "%d-%m-%y %H:%M AEST"
            )

        except ValueError:
            continue

    # Fall back to the more general formatter if the
    # bulletin format changes.
    return format_aest_datetime(value)


def retrieve():
    records, issued, errors = rb.collect()

    source = rb.get_retrieval_source()

    return (
        records,
        issued,
        errors,
        source,
    )

def csv_bytes(df):
    export = df.copy()
    if "station" in export:
        export["station"] = export["station"].astype(str)
    return export.to_csv(index=False).encode("utf-8-sig")

# =========================================================
# Excel daily-record generation
# =========================================================

EXCEL_TEMPLATE_PATH = Path(
    __file__
).with_name(
    "FloodWarningSystem_Template.xlsx"
)


def normalise_gauge(value):
    """
    Convert a gauge identifier to a six-character text value.

    Examples:
        40135  -> 040135
        40793  -> 040793
        40831  -> 040831
        540250 -> 540250
    """

    if value is None:
        return ""

    if isinstance(value, float):
        if pd.isna(value):
            return ""

        if value.is_integer():
            value = int(value)

    digits = "".join(
        character
        for character in str(value)
        if character.isdigit()
    )

    if not digits:
        return ""

    return digits.zfill(6)


def excel_safe_value(value):
    """
    Return None for missing pandas values so Excel receives
    a genuinely blank cell instead of 'nan' or 'None'.
    """

    if value is None:
        return None

    try:
        if pd.isna(value):
            return None

    except (
        TypeError,
        ValueError,
    ):
        pass

    return value


def gauge_row_lookup(
    worksheet,
    first_row,
    last_row,
):
    """
    Read the prefilled gauge numbers from column B and return:

        {
            "040135": 3,
            "540387": 4,
            ...
        }

    The app therefore matches by gauge number rather than relying
    on the template rows being in exactly the same order as Streamlit.
    """

    lookup = {}

    for row_number in range(
        first_row,
        last_row + 1,
    ):
        gauge = normalise_gauge(
            worksheet.cell(
                row=row_number,
                column=2,
            ).value
        )

        if gauge:
            lookup[gauge] = row_number

    return lookup


def populate_forecast_rows(
    worksheet,
    forecast_rows,
):
    """
    Populate the Rainfall Forecast section.

    Rows:
        3–8

    Columns populated:
        E = 1 Day Forecast
        F = 3 Day Forecast
        G = 5 Day Forecast

    All other cells remain untouched.
    """

    row_lookup = gauge_row_lookup(
        worksheet,
        first_row=3,
        last_row=8,
    )

    for record in forecast_rows:
        gauge = normalise_gauge(
            record.get("Station Number")
        )

        row_number = row_lookup.get(
            gauge
        )

        if row_number is None:
            continue

        # E: 1 Day Forecast
        worksheet.cell(
            row=row_number,
            column=5,
        ).value = excel_safe_value(
            record.get("1 Day Forecast")
        )

        # F: 3 Day Forecast
        worksheet.cell(
            row=row_number,
            column=6,
        ).value = excel_safe_value(
            record.get("3 Day Forecast")
        )

        # G: 5 Day Forecast
        worksheet.cell(
            row=row_number,
            column=7,
        ).value = excel_safe_value(
            record.get("5 Day Forecast")
        )


def populate_observed_rainfall_rows(
    worksheet,
    rainfall_table,
):
    """
    Populate observed-rainfall rows 10:15.

    E = Past 3 Hours
    F = Past 6 Hours
    G = Current Rainfall Period or Past 24 Hours
    H = Past 2 Days
    """

    row_lookup = gauge_row_lookup(
        worksheet,
        first_row=10,
        last_row=15,
    )

    if (
        "Past 24 hours (mm)"
        in rainfall_table.columns
    ):
        daily_column_name = (
            "Past 24 hours (mm)"
        )

        worksheet["G9"] = (
            "Past 24 Hours"
        )

    else:
        daily_column_name = (
            "Current rainfall period (mm)"
        )

        worksheet["G9"] = (
            "Current Rainfall Period"
        )

    for _, record in rainfall_table.iterrows():
        gauge = normalise_gauge(
            record.get("Station number")
        )

        row_number = row_lookup.get(
            gauge
        )

        if row_number is None:
            continue

        # E: Past 3 Hours
        worksheet.cell(
            row=row_number,
            column=5,
        ).value = excel_safe_value(
            record.get(
                "Past 3 hours (mm)"
            )
        )

        # F: Past 6 Hours
        worksheet.cell(
            row=row_number,
            column=6,
        ).value = excel_safe_value(
            record.get(
                "Past 6 hours (mm)"
            )
        )

        # G: Dynamic daily rainfall value
        worksheet.cell(
            row=row_number,
            column=7,
        ).value = excel_safe_value(
            record.get(
                daily_column_name
            )
        )

        # H: Past 2 Days
        worksheet.cell(
            row=row_number,
            column=8,
        ).value = excel_safe_value(
            record.get(
                "Past 2 days (mm)"
            )
        )


def populate_river_rows(
    worksheet,
    river_records,
):
    """
    Populate the Current River Levels section.

    Template layout:
        B17:B28 = Gauge numbers, prefilled
        C17:C28 = Locations, prefilled
        D17:D28 = Links, prefilled
        E17:E28 = Observation Time
        F17:F28 = Current River Level
        J17:J28 = Rising/Falling/Steady

    The function does not modify:
        A = Risk Element
        B = Gauges
        C = Location
        D = Link
        G:I = Other template fields
    """

    row_lookup = gauge_row_lookup(
        worksheet,
        first_row=17,
        last_row=28,
    )

    for record in river_records:
        gauge = normalise_gauge(
            record.get("Gauge Number")
        )

        row_number = row_lookup.get(
            gauge
        )

        if row_number is None:
            continue

        # E: Observation Time
        observation_time_cell = worksheet.cell(
            row=row_number,
            column=5,
        )

        observation_time_cell.value = excel_safe_value(
            record.get("Observation Time")
        )

        # F: Current River Level
        river_level_cell = worksheet.cell(
            row=row_number,
            column=6,
        )

        river_level_cell.value = excel_safe_value(
            record.get(
                "Current River Level (m)"
            )
        )

        # Keep the value numeric but display the unit.
        river_level_cell.number_format = '0.00" m"'

        # J: Rising/Falling/Steady
        tendency_cell = worksheet.cell(
            row=row_number,
            column=10,
        )

        tendency_cell.value = excel_safe_value(
            record.get(
                "Rising/Falling/Steady"
            )
        )


def build_completed_excel(
    forecast_rows,
    rainfall_table,
    river_records,
):
    """
    Open the Excel template, populate a fresh copy in memory and
    return the completed workbook as bytes.

    The original template in GitHub is never edited or overwritten.
    """

    if not EXCEL_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            "FloodWarningSystem_Template.xlsx was not found "
            "beside streamlit_app.py."
        )

    workbook = load_workbook(
        EXCEL_TEMPLATE_PATH
    )

    # Use the first worksheet in the template.
    worksheet = workbook.active

    populate_forecast_rows(
        worksheet,
        forecast_rows,
    )

    populate_observed_rainfall_rows(
        worksheet,
        rainfall_table,
    )

    populate_river_rows(
        worksheet,
        river_records,
    )

    output = BytesIO()

    workbook.save(
        output
    )

    output.seek(0)

    return output.getvalue()

st.title("Rainfall Data Extractor")
st.caption("Selected BoM flood-warning gauges: Moogerah, Warrill View, Mount Walker, Rosewood, Lyons and Ipswich")

st.markdown(
    """
    <style>
    .st-key-floating-rainfall-refresh {
        position: fixed;
        top: 4.5rem;
        right: 1.25rem;
        z-index: 999999;
        width: auto;
        padding: 0.35rem;
        border-radius: 0.75rem;
        background: rgba(255, 255, 255, 0.96);
        border: 1px solid rgba(128, 128, 128, 0.35);
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.15);
        backdrop-filter: blur(8px);
    }

    .st-key-floating-rainfall-refresh button {
        white-space: nowrap;
    }

    /* Green Excel download button */
    .st-key-green_excel_download
    [data-testid="stDownloadButton"] button,
    .st-key-green-excel-download
    [data-testid="stDownloadButton"] button {
        background-color: #18864b !important;
        color: #ffffff !important;
        border: 1px solid #18864b !important;
        font-weight: 600 !important;
    }

    .st-key-green_excel_download
    [data-testid="stDownloadButton"] button:hover,
    .st-key-green-excel-download
    [data-testid="stDownloadButton"] button:hover {
        background-color: #126a3a !important;
        color: #ffffff !important;
        border-color: #126a3a !important;
    }

    .st-key-green_excel_download
    [data-testid="stDownloadButton"] button:focus,
    .st-key-green-excel-download
    [data-testid="stDownloadButton"] button:focus {
        background-color: #18864b !important;
        color: #ffffff !important;
        border-color: #18864b !important;
        box-shadow:
            0 0 0 0.2rem
            rgba(24, 134, 75, 0.3) !important;
    }

    .st-key-green_excel_download
    [data-testid="stDownloadButton"] button p,
    .st-key-green-excel-download
    [data-testid="stDownloadButton"] button p {
        color: #ffffff !important;
    }

    @media (prefers-color-scheme: dark) {
        .st-key-floating-rainfall-refresh {
            background: rgba(30, 30, 30, 0.96);
        }
    }

    @media (max-width: 600px) {
        .st-key-floating-rainfall-refresh {
            top: 4.25rem;
            right: 0.75rem;
            bottom: auto;
            max-width: calc(100vw - 1.5rem);
        }

        .st-key-floating-rainfall-refresh button {
            font-size: 0.85rem;
            padding: 0.4rem 0.65rem;
            white-space: nowrap;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
with st.container(
    key="floating-rainfall-refresh",
):
    retrieve_clicked = st.button(
        "Retrieve Latest Rainfall",
        type="primary",
        key="retrieve_latest_rainfall",
        width="content",
    )


if retrieve_clicked or "records" not in st.session_state:
    with st.spinner(
        "Retrieving and checking rainfall data..."
    ):
        records, issued, errors, source = retrieve()

    st.session_state.update(
        records=records,
        issued=issued,
        errors=errors,
        source=source,
        fetched_at=datetime.now(
            rb.AEST
        ).isoformat(timespec="seconds"),
    )

records = st.session_state.get("records", [])
errors = st.session_state.get("errors", [])
df = dataframe(records)

if errors:
    with st.expander(f"Retrieval warnings ({len(errors)})", expanded=not bool(records)):
        for error in errors:
            st.warning(error)

if df.empty:
    st.error(
        "No rainfall readings were retrieved. "
        "The BoM connection may be temporarily unavailable."
    )

    st.info(
        "Try Retrieve Latest Rainfall again. If the issue continues, "
        "review Technical Tools at the bottom of the page."
    )

    st.stop()



st.subheader("Rainfall Forecasts")

st.caption(
    "Cumulative Rain Amount forecasts from Elders Weather. "
    "The 1 Day Forecast includes Today and Tomorrow. "
    "The 3 Day Forecast includes Today through three days ahead. "
    "The 5 Day Forecast includes Today through five days ahead."
)

forecast_refresh = st.button(
    "Refresh rainfall forecasts",
    key="forecast_refresh",
)

if (
    forecast_refresh
    or "forecast_rows" not in st.session_state
):
    with st.spinner(
        "Retrieving rainfall forecasts..."
    ):
        forecast_rows, forecast_errors = (
            forecast.collect_forecasts()
        )

    st.session_state.forecast_rows = forecast_rows
    st.session_state.forecast_errors = forecast_errors

forecast_rows = st.session_state.get(
    "forecast_rows",
    [],
)

forecast_errors = st.session_state.get(
    "forecast_errors",
    [],
)

if forecast_errors:
    with st.expander(
        f"Forecast retrieval warnings "
        f"({len(forecast_errors)})",
        expanded=False,
    ):
        for forecast_error in forecast_errors:
            st.warning(forecast_error)

if forecast_rows:
    forecast_df = pd.DataFrame(
        forecast_rows
    )

    forecast_location_order = [
        "Moogerah",
        "Warrill View",
        "Mount Walker",
        "Rosewood",
        "Lyons",
        "Ipswich",
    ]

    forecast_df["Location"] = pd.Categorical(
        forecast_df["Location"],
        categories=forecast_location_order,
        ordered=True,
    )

    forecast_df = (
        forecast_df
        .sort_values("Location")
        .reset_index(drop=True)
    )

    st.dataframe(
        forecast_df,
        hide_index=True,
        width="stretch",
    )

    st.caption(
        "Forecast values are cumulative rainfall ranges. "
        "The lower bounds and upper bounds of each daily "
        "forecast are summed separately. A blank means the "
        "forecast could not be retrieved for that location."
    )
st.divider()

# =========================================================
# Observed rainfall
# =========================================================

st.subheader("Rainfall Occurred")

source_left, source_middle, source_right = st.columns(3)

source_left.metric(
    "Data source",
    st.session_state.get(
        "source",
        "Unknown",
    ),
)

source_middle.metric(
    "Latest bulletin issued",
    format_aest_datetime(
        latest_bulletin_time(
            st.session_state.get(
                "issued"
            )
        )
    ),
)

source_right.metric(
    "Retrieved by app",
    format_aest_datetime(
        st.session_state.get(
            "fetched_at"
        )
    ),
)

rainfall_summary = latest_table(
    df
)

if "Past 24 hours (mm)" in rainfall_summary.columns:
    daily_column_name = "Past 24 hours (mm)"
else:
    daily_column_name = (
        "Current rainfall period (mm)"
    )

st.dataframe(
    rainfall_summary,
    hide_index=True,
    width="stretch",
    column_config={
        "Station number": (
            st.column_config.TextColumn(
                width="small"
            )
        ),
        "Location": (
            st.column_config.TextColumn(
                width="medium"
            )
        ),
        "Past 3 hours (mm)": (
            st.column_config.NumberColumn(
                format="%.1f"
            )
        ),
        "Past 6 hours (mm)": (
            st.column_config.NumberColumn(
                format="%.1f"
            )
        ),
        daily_column_name: (
            st.column_config.NumberColumn(
                format="%.1f"
            )
        ),
        "Past 2 days (mm)": (
            st.column_config.NumberColumn(
                format="%.1f"
            )
        ),
        "Hourly data warning": (
            st.column_config.TextColumn(
                "Hourly data warning",
                width="large",
            )
        ),
    },
)

stations_with_hourly_warnings = (
    rainfall_summary[
        rainfall_summary[
            "Hourly data warning"
        ].fillna("").ne("")
    ]
)

if not stations_with_hourly_warnings.empty:
    st.warning(
        f"{len(stations_with_hourly_warnings)} "
        "station(s) have incomplete hourly rainfall data. "
        "Missing hourly readings were treated as 0 for the "
        "3-hour and 6-hour totals. Review the warning column "
        "before using these values."
    )

daily_warning = rainfall_daily_warning(
    df
)

if daily_warning:
    st.warning(
        daily_warning
    )

if daily_column_name == "Past 24 hours (mm)":
    st.caption(
        "Past 24 hours is the latest completed BoM daily "
        "period ending at 9 am. Past 2 days is the sum of "
        "the latest two completed daily periods. Missing "
        "observations are not treated as zero."
    )
else:
    st.caption(
        "Current rainfall period is the accumulating BoM "
        "value since 9 am. Past 2 days combines that current "
        "period with the immediately preceding completed "
        "24-hour period. The current period is not an exact "
        "rolling 24-hour total. Missing observations are not "
        "treated as zero."
    )
st.divider()

st.subheader("Current River Levels")

river_refresh = st.button(
    "Retrieve current river levels",
    key="river_level_refresh",
)

if (
    river_refresh
    or "river_level_records"
    not in st.session_state
):
    try:
        river_records, river_issued, river_source = (
            river.collect_river_levels()
        )

        st.session_state.river_level_records = (
            river_records
        )

        st.session_state.river_level_issued = (
            river_issued
        )

        st.session_state.river_level_source = (
            river_source
        )
        st.session_state.river_level_retrieved_at = (
            datetime.now(
                rb.AEST
            ).isoformat(
                timespec="seconds"
            )
        )
        
        st.session_state.river_level_error = None

    except Exception as exc:
        st.session_state.river_level_error = (
            str(exc)
        )

if st.session_state.get("river_level_error"):
    st.warning(st.session_state.river_level_error)

river_records = st.session_state.get(
    "river_level_records",
    [],
)

if river_records:
    river_df = pd.DataFrame(
        river_records
    )

    # Preserve six-character gauge numbers.
    river_df["Gauge Number"] = (
        river_df["Gauge Number"]
        .astype(str)
        .str.zfill(6)
    )

    # Enforce one row per gauge.
    river_df = (
        river_df
        .drop_duplicates(
            subset=["Gauge Number"],
            keep="first",
        )
        .reset_index(drop=True)
    )

    river_gauge_order = [
        "540065",
        "540062",
        "540057",
        "540387",
        "540180",
        "540157",
        "540388",
        "540147",
        "540504",
        "040836",
        "540250",
        "040831",
    ]

    river_df["Gauge Number"] = pd.Categorical(
        river_df["Gauge Number"],
        categories=river_gauge_order,
        ordered=True,
    )

    river_df = (
        river_df
        .sort_values("Gauge Number")
        .reset_index(drop=True)
    )

    unique_river_gauges = len(
        river_df[
            "Gauge Number"
        ].dropna().unique()
    )

    if unique_river_gauges != 12:
        st.warning(
            f"Expected 12 unique river gauges but received "
            f"{unique_river_gauges}."
        )

    info_left, info_middle, info_right = st.columns(3)

    info_left.metric(
        "Data source",
        st.session_state.get(
            "river_level_source",
            "Unknown",
        ),
    )

    info_middle.metric(
        "Bulletin issued",
        format_bom_issue_datetime(
            st.session_state.get(
                "river_level_issued"
            )
        ),
    )

    info_right.metric(
        "Retrieved by app",
        format_aest_datetime(
            st.session_state.get(
                "river_level_retrieved_at"
            )
        ),
    )

    # Header + 12 gauge rows + horizontal-scroll allowance.

    river_table_height = (
    32
    + len(river_df) * 35
    )

    st.dataframe(
        river_df,
        hide_index=True,
        width="stretch",
        height=river_table_height,
        column_config={
            "Gauge Number": (
                st.column_config.TextColumn()
            ),
            "Current River Level (m)": (
                st.column_config.NumberColumn(
                    format="%.2f m"
                )
            ),
        },
    )

    st.caption(
        "Current River Level is adopted from Height (m). "
        "Rising/Falling/Steady is adopted from Tendency."
    )    

else:
    st.info(
        "No current river-level records are available."
    )

# =========================================================
# Completed Excel daily record
# =========================================================

st.divider()

st.subheader("Daily Record Sheet")

st.caption(
    "Download the current rainfall forecasts, observed rainfall "
    "and river levels into the formatted Excel template."
)

forecast_for_excel = st.session_state.get(
    "forecast_rows",
    [],
)

rainfall_for_excel = latest_table(
    df
)

river_for_excel = st.session_state.get(
    "river_level_records",
    [],
)

excel_ready = (
    bool(forecast_for_excel)
    and not rainfall_for_excel.empty
    and bool(river_for_excel)
)

if excel_ready:
    try:
        completed_excel = build_completed_excel(
            forecast_rows=forecast_for_excel,
            rainfall_table=rainfall_for_excel,
            river_records=river_for_excel,
        )

        download_timestamp = datetime.now(
            rb.AEST
        ).strftime(
            "%Y-%m-%d_%H%M"
        )

        with st.container(
            key="green_excel_download",
        ):
            st.download_button(
                "Download Completed Daily Record (.xlsx)",
                data=completed_excel,
                file_name=(
                    "FloodWarningSystem_"
                    f"{download_timestamp}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                width="stretch",
                key="download_completed_daily_record",
        )

    except Exception as exc:
        st.error(
            f"Could not create the Excel daily record: {exc}"
        )

else:
    missing_sections = []

    if not forecast_for_excel:
        missing_sections.append(
            "rainfall forecasts"
        )

    if rainfall_for_excel.empty:
        missing_sections.append(
            "observed rainfall"
        )

    if not river_for_excel:
        missing_sections.append(
            "river levels"
        )

    st.info(
        "Retrieve "
        + ", ".join(missing_sections)
        + " before downloading the completed daily record."
    )

st.divider()

with st.expander(
    "Technical Tools",
    expanded=False,
):
    st.caption(
        "Detailed source readings, technical downloads, data notes "
        "and connection diagnostics."
    )

    (
        detailed_tab,
        snapshot_tab,
        notes_tab,
        ftp_tab,
    ) = st.tabs(
        [
            "Detailed readings",
            "JSON snapshot",
            "Data notes",
            "BoM FTP test",
        ]
    )

    # =========================================================
    # Detailed rainfall readings
    # =========================================================

    with detailed_tab:
        st.caption(
            "Verification data showing the exact BoM source station "
            "and individual observation periods used by the app."
        )

        filter_left, filter_right = st.columns(2)

        selected_stations = filter_left.multiselect(
            "Locations",
            STATION_ORDER,
            default=STATION_ORDER,
            key="technical_locations",
        )

        selected_periods = filter_right.multiselect(
            "Rainfall periods",
            list(SERIES_LABELS),
            default=list(SERIES_LABELS),
            format_func=lambda value: SERIES_LABELS[value],
            key="technical_rainfall_periods",
        )

        filtered = df[
            df["station"].isin(selected_stations)
            & df["series"].isin(selected_periods)
        ].copy()

        display = filtered[
            [
                "station_id",
                "station",
                "bom_station",
                "period",
                "period_start",
                "period_end",
                "rainfall_mm",
                "issued",
            ]
        ].copy()

        display.columns = [
            "Station number",
            "Location",
            "BoM source station",
            "Period",
            "Period start (AEST)",
            "Period end (AEST)",
            "Rainfall (mm)",
            "Bulletin issued (AEST)",
        ]

        st.dataframe(
            display,
            hide_index=True,
            width="stretch",
            column_config={
                "Rainfall (mm)": st.column_config.NumberColumn(
                    format="%.1f"
                ),
            },
        )

        st.download_button(
            "Download filtered readings (CSV)",
            csv_bytes(display),
            file_name="bom_rainfall_readings.csv",
            mime="text/csv",
            width="stretch",
            key="download_detailed_rainfall",
        )

    # =========================================================
    # Complete JSON snapshot
    # =========================================================

    with snapshot_tab:
        st.caption(
            "Download the complete rainfall retrieval result for "
            "troubleshooting and verification."
        )

        snapshot = {
            "fetched_at": st.session_state.get(
                "fetched_at"
            ),
            "source": st.session_state.get(
                "source"
            ),
            "issued": st.session_state.get(
                "issued"
            ),
            "errors": errors,
            "records": records,
        }

        st.download_button(
            "Download complete snapshot (JSON)",
            json.dumps(
                snapshot,
                indent=2,
            ),
            file_name="bom_rainfall_snapshot.json",
            mime="application/json",
            width="stretch",
            key="download_complete_snapshot",
        )

        st.caption(
            "The snapshot includes every retrieved rainfall record, "
            "bulletin issue times, retrieval time and reported errors."
        )

    # =========================================================
    # Data notes
    # =========================================================

    with notes_tab:
        st.write(
            "This tool reports operational BoM rainfall and "
            "river-height observations. These observations may "
            "have received only limited quality checking."
        )

        st.write(
            "The Location column contains the application-friendly "
            "location name. The BoM source station field contains "
            "the exact source row matched by the rainfall scraper."
        )

        st.write(
            "A blank rainfall or river-level value means no usable "
            "observation was returned. It does not mean zero."
        )

        st.write(
            "Past 6 hours is calculated from the required 3-hour "
            "rainfall periods. Past 2 days is calculated from the "
            "required completed 24-hour rainfall periods."
        )

        st.write(
            "Rainfall forecast values are cumulative forecast ranges. "
            "Lower and upper bounds are summed separately."
        )

        st.write(
            "Kalbar river level is reported in metres AHD. Other "
            "river gauges may be reported using Local Gauge Height, "
            "so the values should not be compared without considering "
            "their respective datums."
        )

        if st.session_state.get("issued"):
            st.write("Rainfall bulletin issue times:")

            st.json(
                st.session_state["issued"]
            )

        if st.session_state.get("river_level_issued"):
            st.write(
                "River bulletin issued:"
            )

            st.code(
                str(
                    st.session_state[
                        "river_level_issued"
                    ]
                )
            )

    # =========================================================
    # BoM FTP connection test
    # =========================================================

    with ftp_tab:
        st.caption(
            "Checks whether the Streamlit server can access the "
            "BoM anonymous FTP service and find the required "
            "rainfall products."
        )

        if st.button(
            "Test BoM FTP Connection",
            key="test_bom_ftp",
        ):
            try:
                with st.spinner(
                    "Testing BoM FTP connection..."
                ):
                    ftp_result = (
                        rb.test_ftp_connection()
                    )

                st.success(
                    "Connected successfully to BoM FTP."
                )

                st.write(
                    f"Host: {ftp_result['host']}"
                )

                st.write(
                    "Directory: "
                    f"{ftp_result['directory']}"
                )

                if ftp_result.get("files"):
                    st.write(
                        "Expected rainfall files found:"
                    )

                    for filename in ftp_result["files"]:
                        st.code(filename)

                if ftp_result.get("missing"):
                    st.warning(
                        "Expected rainfall files not found:"
                    )

                    for filename in ftp_result["missing"]:
                        st.code(filename)

                if not ftp_result.get("missing"):
                    st.success(
                        "All expected rainfall products were found."
                    )

            except Exception as exc:
                st.error(
                    f"BoM FTP connection failed: {exc}"
                )

                st.info(
                    "If an HTTPS fallback is configured in "
                    "rainfall_backend.py, the app can continue "
                    "retrieving rainfall without FTP."
                )
            st.write(
                "Rainfall retrieval methods:"
            )

            if rb.LAST_RETRIEVAL_METHOD:
                for product, method in (
                    rb.LAST_RETRIEVAL_METHOD.items()
                ):
                    st.write(
                        f"{product}: {method}"
                    )
            else:
                st.write(
                    "No rainfall retrieval has been completed."
                )
                
