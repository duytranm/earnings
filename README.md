# Earnings Transcripts (FMP)

Streamlit app for browsing earnings call transcripts from the
[Financial Modeling Prep Earnings Transcript API](https://site.financialmodelingprep.com/developer/docs#earnings-transcript).

- **Transcript**: pick a ticker and quarter; search with highlighting, filter by speaker, chart words per speaker, download as .txt
- **Latest calls**: the newest transcripts across all companies; select a row to open it
- **All symbols**: searchable list of every covered company

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The API key comes from `FMP_API_KEY`, `.streamlit/secrets.toml` (see `secrets.toml.example`), or the sidebar.

## Deploy to Streamlit Community Cloud

1. Push this folder to a GitHub repo (`secrets.toml` is git-ignored).
2. Go to https://share.streamlit.io, click **Create app**, choose the repo/branch, and set the main file to `app.py`.
3. Under **Advanced settings → Secrets**, paste:
   ```toml
   FMP_API_KEY = "your_fmp_api_key"
   ```
4. Click **Deploy**.

Note: with the secret set, anyone with the app URL uses your FMP quota. Make the app private in
Streamlit Cloud sharing settings, or leave the secret unset so each visitor enters their own key.
