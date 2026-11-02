# Rainfall Data Extractor

A Streamlit interface for selected Bureau of Meteorology flood-warning gauges.

## Files

- `streamlit_app.py`: web interface and CSV/JSON downloads
- `rainfall_backend.py`: retrieval, parsing and station matching
- `requirements.txt`: Python packages installed by Streamlit Community Cloud

## Deploy on Streamlit Community Cloud

1. Create a new GitHub repository.
2. Upload all three files listed above to the repository root.
3. Sign into https://share.streamlit.io using GitHub.
4. Select **Create app**.
5. Choose the repository and `main` branch.
6. Set the main file path to `streamlit_app.py`.
7. Select **Deploy**.

## Local testing (optional)

```bash
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

## If live BoM retrieval is blocked

Save the official bulletin pages as:

- `1h.html` for IDQ60336
- `3h.html` for IDQ60348
- `24h.html` for IDQ60360

Upload all three in the sidebar and press **Retrieve latest rainfall**.

## Important limitations

- Verify the configured station-number-to-BoM-name mappings before operational use.
- A blank is treated as missing, not zero.
- Streamlit Community Cloud does not provide this app with a durable historical database. Downloads are generated from the current session.
- The live BoM request may be blocked with HTTP 403. If so, manual HTML upload remains available, but a different approved data source or internal hosting arrangement will be needed for fully automatic operation.
