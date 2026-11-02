"""Streamlit front end for selected BoM rainfall gauges."""
from datetime import datetime
import json
import pandas as pd
import streamlit as st
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

    # All completed 3-hour rainfall periods.
    three_hour_data = (
        df[df["series"] == "3h"]
        .sort_values("period_end")
        .copy()
    )

    # Latest completed 3-hour rainfall period.
    past_3_hours = (
        three_hour_data
        .groupby(
            group_columns,
            observed=True,
            group_keys=False,
        )
        .tail(1)[
            [
                "station_id",
                "station",
                "rainfall_mm",
            ]
        ]
        .rename(
            columns={
                "rainfall_mm": "Past 3 hours (mm)",
            }
        )
    )

    # Sum the latest two completed 3-hour rainfall periods.
    past_6_hours = (
        three_hour_data
        .groupby(
            group_columns,
            observed=True,
            group_keys=False,
        )
        .tail(2)
        .groupby(
            group_columns,
            observed=True,
            as_index=False,
        )
        .agg(
            **{
                "Past 6 hours (mm)": (
                    "rainfall_mm",
                    lambda values: (
                        values.sum()
                        if (
                            len(values) == 2
                            and values.notna().sum() == 2
                        )
                        else None
                    ),
                )
            }
        )
    )

    # All completed 24-hour rainfall periods.
    daily_data = (
        df[df["series"] == "24h"]
        .sort_values("period_end")
        .copy()
    )

    # Latest completed 24-hour rainfall period.
    past_1_day = (
        daily_data
        .groupby(
            group_columns,
            observed=True,
            group_keys=False,
        )
        .tail(1)[
            [
                "station_id",
                "station",
                "rainfall_mm",
            ]
        ]
        .rename(
            columns={
                "rainfall_mm": "Past 1 day (mm)",
            }
        )
    )

    # Sum the latest two completed 24-hour rainfall periods.
    past_2_days = (
        daily_data
        .groupby(
            group_columns,
            observed=True,
            group_keys=False,
        )
        .tail(2)
        .groupby(
            group_columns,
            observed=True,
            as_index=False,
        )
        .agg(
            **{
                "Past 2 days (mm)": (
                    "rainfall_mm",
                    lambda values: (
                        values.sum()
                        if (
                            len(values) == 2
                            and values.notna().sum() == 2
                        )
                        else None
                    ),
                )
            }
        )
    )

    # Create the station framework first so all configured
    # locations remain visible even if a period is missing.
    table = pd.DataFrame(
        [
            {
                "station_id": station["id"],
                "station": station["label"],
            }
            for station in rb.STATIONS
        ]
    )

    table = (
        table
        .merge(
            past_3_hours,
            on=group_columns,
            how="left",
        )
        .merge(
            past_6_hours,
            on=group_columns,
            how="left",
        )
        .merge(
            past_1_day,
            on=group_columns,
            how="left",
        )
        .merge(
            past_2_days,
            on=group_columns,
            how="left",
        )
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

def retrieve():
    records, issued, errors = rb.collect()

    return (
        records,
        issued,
        errors,
        "BoM live rainfall bulletins",
    )

def csv_bytes(df):
    export = df.copy()
    if "station" in export:
        export["station"] = export["station"].astype(str)
    return export.to_csv(index=False).encode("utf-8-sig")

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

    @media (prefers-color-scheme: dark) {
        .st-key-floating-rainfall-refresh {
            background: rgba(30, 30, 30, 0.96);
        }
    }

    @media (max-width: 600px) {
        .st-key-floating-rainfall-refresh {
            top: auto;
            right: 0.75rem;
            bottom: 1rem;
            max-width: calc(100vw - 1.5rem);
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

meta1, meta2 = st.columns(2)
meta1.metric("Data source", st.session_state.get("source", "Unknown"))
meta2.metric("Retrieved", st.session_state.get("fetched_at", "Unknown").replace("T", " "))

st.subheader("Latest rainfall totals")

st.dataframe(
    latest_table(df),
    hide_index=True,
    width="stretch",
    column_config={
        "Past 3 hours (mm)": st.column_config.NumberColumn(
            format="%.1f"
        ),
        "Past 6 hours (mm)": st.column_config.NumberColumn(
            format="%.1f"
        ),
        "Past 1 day (mm)": st.column_config.NumberColumn(
            format="%.1f"
        ),
        "Past 2 days (mm)": st.column_config.NumberColumn(
            format="%.1f"
        ),
    },
)

st.caption(
    "Past 6 hours is the sum of the latest two completed "
    "3-hour rainfall periods. Past 2 days is the sum of the "
    "latest two completed 24-hour rainfall periods. A blank "
    "means one or more required observations were unavailable."
)

st.caption("A blank cell means no observation was reported for that gauge and period. It does not mean zero rainfall.")

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
st.header("Current River Levels")
st.caption("Selected river-height observations from BoM bulletin IDQ60286.")

river_refresh = st.button("Retrieve current river levels", key="river_level_refresh")

if river_refresh or "river_level_records" not in st.session_state:
    try:
        river_records, river_issued, river_source = (
        river.collect_river_levels()
        )
        st.session_state.river_level_records = river_records
        st.session_state.river_level_issued = river_issued
        st.session_state.river_level_source = river_source
        st.session_state.river_level_error = None
    except Exception as exc:
        st.session_state.river_level_error = str(exc)

if st.session_state.get("river_level_error"):
    st.warning(st.session_state.river_level_error)

river_records = st.session_state.get("river_level_records", [])
if river_records:
    river_df = pd.DataFrame(river_records)
    info_left, info_right = st.columns(2)
    info_left.metric("River data source", st.session_state.get("river_level_source", "Unknown"))
    info_right.metric("River bulletin issued", st.session_state.get("river_level_issued") or "Unknown")

    st.dataframe(
        river_df,
        hide_index=True,
        width="stretch",
        column_config={
            "Current River Level (m)": st.column_config.NumberColumn(format="%.2f m"),
        },
    )
    st.download_button(
        "Download river levels (CSV)",
        river_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="bom_current_river_levels.csv",
        mime="text/csv",
        key="download_river_levels",
    )
    st.caption("Current River Level is scraped from Height (m). Rising/Falling/Steady is scraped from Tendency.")

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
