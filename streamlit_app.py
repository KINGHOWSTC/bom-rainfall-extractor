"""Streamlit front end for selected BoM rainfall gauges."""
from datetime import datetime
import csv
import io
import json
import pandas as pd
import streamlit as st
import rainfall_backend as rb
import river_level_backend as river

st.set_page_config(page_title="Rainfall Data Extractor", page_icon="🌧️", layout="wide")

SERIES_LABELS = {
    "1h": "1-hour rainfall",
    "3h": "3-hour rainfall",
    "24h": "24-hour rainfall to 9 am",
    "since_9am": "Rainfall since 9 am",
}
STATION_ORDER = [s["label"] for s in rb.STATIONS]

def read_uploads(files):
    """Return product-keyed HTML from files named 1h, 3h and 24h."""
    result = {}
    for file in files or []:
        name = file.name.lower()
        key = next((k for k in rb.BULLETINS if k in name), None)
        if key:
            result[key] = file.getvalue().decode("utf-8", errors="replace")
    return result

def collect_uploaded(uploaded):
    records, issued, errors = [], {}, []
    for key in rb.BULLETINS:
        if key not in uploaded:
            errors.append(f"{key}: no uploaded file found; include '{key}' in its filename")
            continue
        try:
            issue_time, rows = rb.parse_bulletin(uploaded[key], key)
            issued[key] = issue_time.isoformat()
            records.extend(rb.station_records(rows, issue_time, key))
        except rb.BulletinError as exc:
            errors.append(f"{key}: {exc}")
    return records, issued, errors

def retrieve(uploaded_files):
    uploaded = read_uploads(uploaded_files)
    if uploaded:
        return (*collect_uploaded(uploaded), "Uploaded HTML")
    records, issued, errors = rb.collect()
    return records, issued, errors, "Live BoM bulletins"

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
        return df
    latest = (df.sort_values("period_end")
                .groupby(["station_id", "station", "series"], observed=True, as_index=False)
                .tail(1))
    table = latest.pivot(index=["station_id", "station"], columns="series", values="rainfall_mm")
    table = table.reindex(columns=["1h", "3h", "24h", "since_9am"]).reset_index()
    table.columns.name = None
    return table.rename(columns={
        "station_id": "Station number", "station": "Station",
        "1h": "Latest 1 h (mm)", "3h": "Latest 3 h (mm)",
        "24h": "24 h to 9 am (mm)", "since_9am": "Since 9 am (mm)",
    })

def csv_bytes(df):
    export = df.copy()
    if "station" in export:
        export["station"] = export["station"].astype(str)
    return export.to_csv(index=False).encode("utf-8-sig")

st.title("Rainfall Data Extractor")
st.caption("Selected BoM flood-warning gauges: Moogerah, Warrill View, Mount Walker, Rosewood, Lyons and Ipswich")

with st.sidebar:
    st.header("Retrieve data")
    uploads = st.file_uploader(
        "Optional saved bulletin pages",
        type=["html", "htm"], accept_multiple_files=True,
        help="Only use this if live retrieval is blocked. Name the files 1h.html, 3h.html and 24h.html.",
    )
    retrieve_clicked = st.button("Retrieve latest rainfall", type="primary", use_container_width=True)
    st.caption("With no uploads, the app requests the three live BoM bulletins. Uploaded pages override live retrieval.")

if retrieve_clicked or "records" not in st.session_state:
    with st.spinner("Retrieving and checking rainfall data..."):
        records, issued, errors, source = retrieve(uploads)
    st.session_state.update(records=records, issued=issued, errors=errors, source=source,
                            fetched_at=datetime.now(rb.AEST).isoformat(timespec="seconds"))

records = st.session_state.get("records", [])
errors = st.session_state.get("errors", [])
df = dataframe(records)

if errors:
    with st.expander(f"Retrieval warnings ({len(errors)})", expanded=not bool(records)):
        for error in errors:
            st.warning(error)

if df.empty:
    st.error("No rainfall readings were retrieved. BoM may have blocked the request, or its page layout may have changed.")
    st.info("Fallback: save the three BoM pages as 1h.html, 3h.html and 24h.html, upload them in the sidebar, then click Retrieve latest rainfall.")
    st.stop()

meta1, meta2 = st.columns(2)
meta1.metric("Data source", st.session_state.get("source", "Unknown"))
meta2.metric("Retrieved", st.session_state.get("fetched_at", "Unknown").replace("T", " "))

st.subheader("Latest rainfall totals")
st.dataframe(latest_table(df), hide_index=True, use_container_width=True,
             column_config={c: st.column_config.NumberColumn(format="%.1f") for c in
                            ["Latest 1 h (mm)", "Latest 3 h (mm)", "24 h to 9 am (mm)", "Since 9 am (mm)"]})
st.caption("A blank cell means no observation was reported for that gauge and period. It does not mean zero rainfall.")

st.subheader("Detailed readings")
left, right = st.columns(2)
selected_stations = left.multiselect("Stations", STATION_ORDER, default=STATION_ORDER)
selected_periods = right.multiselect("Rainfall periods", list(SERIES_LABELS), default=list(SERIES_LABELS),
                                     format_func=lambda x: SERIES_LABELS[x])
filtered = df[df["station"].isin(selected_stations) & df["series"].isin(selected_periods)].copy()
display = filtered[["station_id", "station", "bom_station", "period", "period_start", "period_end", "rainfall_mm", "issued"]]
display.columns = ["Station number", "Station", "BoM station", "Period", "Period start (AEST)",
                   "Period end (AEST)", "Rainfall (mm)", "Bulletin issued (AEST)"]
st.dataframe(display, hide_index=True, use_container_width=True,
             column_config={"Rainfall (mm)": st.column_config.NumberColumn(format="%.1f")})

c1, c2 = st.columns(2)
c1.download_button("Download filtered readings (CSV)", csv_bytes(display),
                   file_name="bom_rainfall_readings.csv", mime="text/csv", use_container_width=True)
snapshot = {"fetched_at": st.session_state.get("fetched_at"), "issued": st.session_state.get("issued"),
            "errors": errors, "records": records}
c2.download_button("Download complete snapshot (JSON)", json.dumps(snapshot, indent=2),
                   file_name="bom_rainfall_snapshot.json", mime="application/json", use_container_width=True)

with st.expander("Data notes"):
    st.write("This tool reports BoM bulletin values and does not independently quality-control the gauges.")
    st.write("Station labels are matched to the exact BoM names configured in rainfall_backend.py. Verify the station-number mapping before operational use.")
    if st.session_state.get("issued"):
        st.json(st.session_state["issued"])

# import river_level_backend as river

st.divider()
st.header("Current River Levels")
st.caption("Selected river-height observations from BoM bulletin IDQ60286.")

river_upload = st.file_uploader(
    "Optional saved IDQ60286 river-height page",
    type=["html", "htm", "txt"],
    key="river_level_upload",
    help="Only needed if BoM blocks automatic retrieval.",
)
river_refresh = st.button("Retrieve current river levels", key="river_level_refresh")

if river_refresh or "river_level_records" not in st.session_state:
    try:
        river_html = (river_upload.getvalue().decode("utf-8", errors="replace")
                      if river_upload is not None else None)
        river_records, river_issued, river_source = river.collect_river_levels(river_html)
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
        use_container_width=True,
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
