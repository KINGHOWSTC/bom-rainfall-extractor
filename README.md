# Rainfall Data Extractor

A Streamlit application for retrieving, summarising and exporting rainfall forecasts, observed rainfall and river-level data for a prescribed set of locations in the Brisbane and Bremer River catchments.

> **Important:** This application is configured only for the stations, products and spreadsheet layout listed below. It is not a general-purpose rainfall, river-level or flood-warning application.

## Current functionality

The application provides:

- Cumulative rainfall forecasts for selected locations
- Observed rainfall totals for the past 3 hours, 6 hours, 24 hours and 2 days
- Current river levels, gauge datums and tendencies
- BoM bulletin issue times and application retrieval times
- FTP-first retrieval of BoM rainfall and river-height products
- HTTPS fallback if BoM anonymous FTP is unavailable
- A completed Excel Daily Record Sheet download
- Detailed readings and connection diagnostics under Technical Tools

## Configured rainfall locations

The application is configured for:

| Gauge | Location | BoM source station |
|---|---|---|
| `040135` | Moogerah | Moogerah Dam HG |
| `540387` | Warrill View | Harrisville |
| `540574` | Mount Walker | Lower Mt Walker |
| `540503` | Rosewood | Rosewood Detention Basin |
| `040793` | Lyons | Lyons |
| `540250` | Ipswich | Brassall (Hancocks Bridge) |

## Configured river-level locations

The application is configured for:

| Gauge | Location | BoM source station |
|---|---|---|
| `540388` | Rosewood | Bremer River at Rosewood |
| `540147` | Five Mile Bridge | Bremer River at Five Mile Bridge |
| `540057` | Kalbar | Warrill Creek at Kalbar Weir TW |
| `540504` | Walloon | Bremer River at Walloon |
| `040831` | Ipswich | Bremer River at Ipswich |

## Data sources

### Observed rainfall

The application retrieves these Bureau of Meteorology Queensland products:

| Product | Purpose |
|---|---|
| `IDQ60336` | 1-hour rainfall bulletin |
| `IDQ60348` | 3-hour rainfall bulletin |
| `IDQ60360` | 24-hour rainfall bulletin |

The retrieval order is:

1. BoM anonymous FTP
2. BoM HTTPS HTML fallback

The application reports the retrieval method used for the current rainfall data.

### River levels

Current river levels are retrieved from:

```text
IDQ60286
