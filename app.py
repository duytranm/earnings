"""Streamlit app for browsing FMP earnings call transcripts.

Run:  streamlit run app.py
API key: set FMP_API_KEY, add it to .streamlit/secrets.toml, or paste it in the sidebar.
"""

from __future__ import annotations

import os
import re
from collections import Counter

import pandas as pd
import streamlit as st

from fmp_transcripts import FMPError, FMPTranscriptClient, Transcript

st.set_page_config(page_title="Earnings Transcripts", page_icon=":material/record_voice_over:", layout="wide")


# -- data access (cached) ----------------------------------------------------

def _client(api_key: str) -> FMPTranscriptClient:
    return FMPTranscriptClient(api_key=api_key)


@st.cache_data(ttl="1h", show_spinner=False)
def get_dates(api_key: str, symbol: str) -> list[dict]:
    return _client(api_key).dates(symbol)


@st.cache_data(ttl="1d", show_spinner=False)
def get_transcript(api_key: str, symbol: str, year: int, quarter: int) -> Transcript | None:
    return _client(api_key).transcript(symbol, year, quarter)


@st.cache_data(ttl="15m", show_spinner=False)
def get_latest(api_key: str, page: int, limit: int) -> list[dict]:
    return _client(api_key).latest(page=page, limit=limit)


@st.cache_data(ttl="1d", show_spinner=False)
def get_symbols(api_key: str) -> list[dict]:
    return _client(api_key).symbols()


# -- sidebar -----------------------------------------------------------------

def _default_key() -> str:
    try:
        return st.secrets.get("FMP_API_KEY", "") or os.environ.get("FMP_API_KEY", "")
    except Exception:  # no secrets.toml
        return os.environ.get("FMP_API_KEY", "")


with st.sidebar:
    st.header("Earnings Transcripts")
    api_key = st.text_input(
        "FMP API key", value=_default_key(), type="password",
        help="Read from FMP_API_KEY / secrets.toml if set.",
    )
    st.caption("Data: [Financial Modeling Prep](https://site.financialmodelingprep.com/developer/docs#earnings-transcript)")

if not api_key:
    st.info("Enter your FMP API key in the sidebar to get started.", icon=":material/key:")
    st.stop()

if "symbol" not in st.session_state:
    st.session_state.symbol = "AAPL"


def open_transcript(symbol: str, year: int | None = None, quarter: int | None = None) -> None:
    """Jump the Transcript tab to a given call."""
    st.session_state.symbol = symbol.upper()
    st.session_state.pending_period = (year, quarter) if year and quarter else None
    st.toast(f"Loaded {symbol.upper()} — switch to the Transcript tab.")


# -- views -------------------------------------------------------------------

def render_transcript(t: Transcript, query: str) -> None:
    turns = t.speaker_turns()
    words = len(t.content.split())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Call date", t.date[:10] if t.date else "—")
    c2.metric("Period", f"Q{t.quarter} FY{t.year}")
    c3.metric("Words", f"{words:,}")
    c4.metric("Speakers", len({s for s, _ in turns if s}))

    st.download_button(
        "Download .txt", data=t.content, file_name=f"{t.symbol}_Q{t.quarter}_{t.year}.txt",
        icon=":material/download:",
    )

    view_text, view_speakers = st.tabs(["Transcript", "Speakers"])

    with view_speakers:
        talk = Counter()
        for speaker, text in turns:
            talk[speaker or "Unknown"] += len(text.split())
        df = pd.DataFrame(talk.most_common(), columns=["Speaker", "Words"])
        st.bar_chart(df, x="Speaker", y="Words", horizontal=True, height=max(250, 28 * len(df)))

    with view_text:
        speakers = sorted({s for s, _ in turns if s})
        only = st.multiselect("Filter speakers", speakers, placeholder="All speakers")
        pattern = re.compile(re.escape(query), re.IGNORECASE) if query else None

        shown = 0
        for speaker, text in turns:
            if only and speaker not in only:
                continue
            if pattern and not pattern.search(text):
                continue
            if pattern:
                text = pattern.sub(lambda m: f":orange-background[{m.group(0)}]", text)
            st.markdown(f"**{speaker or 'Unknown'}**  \n{text}")
            shown += 1
        if shown == 0:
            st.warning("No passages match the current filters.")
        elif pattern:
            st.caption(f"{shown} passage(s) match “{query}”.")


def transcript_tab() -> None:
    col_sym, col_period, col_search = st.columns([1, 1, 2])
    symbol = col_sym.text_input("Ticker", key="symbol").strip().upper()
    if not symbol:
        return

    try:
        with st.spinner(f"Loading available calls for {symbol}…"):
            dates = get_dates(api_key, symbol)
    except FMPError as e:
        st.error(str(e))
        return
    if not dates:
        st.warning(f"No transcripts available for {symbol}.")
        return

    options = [(int(d["fiscalYear"]), int(d["quarter"])) for d in dates]
    date_by = {(int(d["fiscalYear"]), int(d["quarter"])): d.get("date", "") for d in dates}

    pending = st.session_state.pop("pending_period", None)
    if pending in options:
        st.session_state.period = pending
    elif st.session_state.get("period") not in options:
        st.session_state.period = options[0]

    year, quarter = col_period.selectbox(
        "Call", options, key="period",
        format_func=lambda p: f"Q{p[1]} FY{p[0]}  ({str(date_by[p])[:10]})",
    )
    query = col_search.text_input("Search transcript", placeholder="e.g. guidance, margin, AI")

    try:
        with st.spinner("Fetching transcript…"):
            t = get_transcript(api_key, symbol, year, quarter)
    except FMPError as e:
        st.error(str(e))
        return
    if not t:
        st.warning("Transcript not available for that period.")
        return

    st.subheader(f"{t.symbol} — Q{t.quarter} FY{t.year} earnings call")
    render_transcript(t, query)


def latest_tab() -> None:
    c1, c2 = st.columns([1, 3])
    limit = c1.select_slider("Rows", [25, 50, 100, 200], value=50)
    try:
        rows = get_latest(api_key, 0, limit)
    except FMPError as e:
        st.error(str(e))
        return
    if not rows:
        st.info("No recent transcripts returned.")
        return

    df = pd.DataFrame(rows)
    st.caption("Select a row to open that call in the Transcript tab.")
    event = st.dataframe(
        df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        key="latest_table",
    )
    sel = event.selection.rows
    if sel:
        row = df.iloc[sel[0]]
        period = str(row.get("period", "")).upper().lstrip("Q")
        year = int(row.get("fiscalYear") or row.get("year") or 0)
        st.button(
            f"Open {row['symbol']} Q{period} FY{year}", type="primary", icon=":material/open_in_new:",
            on_click=open_transcript, args=(row["symbol"], year, int(period) if period.isdigit() else None),
        )


def symbols_tab() -> None:
    try:
        with st.spinner("Loading symbol list…"):
            df = pd.DataFrame(get_symbols(api_key))
    except FMPError as e:
        st.error(str(e))
        return
    if df.empty:
        st.info("No symbols returned.")
        return

    q = st.text_input("Search symbol or company", placeholder="e.g. NVDA or Microsoft")
    if q:
        mask = df.apply(lambda r: r.astype(str).str.contains(q, case=False, regex=False).any(), axis=1)
        df = df[mask]
    st.caption(f"{len(df):,} companies")
    event = st.dataframe(
        df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        key="symbols_table",
    )
    if event.selection.rows:
        sym = df.iloc[event.selection.rows[0]]["symbol"]
        st.button(f"Open {sym}", type="primary", icon=":material/open_in_new:",
                  on_click=open_transcript, args=(sym,))


tab_t, tab_l, tab_s = st.tabs(["Transcript", "Latest calls", "All symbols"])
with tab_t:
    transcript_tab()
with tab_l:
    latest_tab()
with tab_s:
    symbols_tab()
