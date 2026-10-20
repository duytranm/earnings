"""Client for the Financial Modeling Prep (FMP) Earnings Transcript API.

Docs: https://site.financialmodelingprep.com/developer/docs#earnings-transcript

Endpoints covered (stable API):
  - earning-call-transcript-latest   latest transcripts across all companies
  - earning-call-transcript          full transcript for symbol/year/quarter
  - earning-call-transcript-dates    available fiscal year/quarter/date per symbol
  - earnings-transcript-list         all symbols with transcripts + counts

Stdlib only. The API key is read from the FMP_API_KEY environment variable
(or passed explicitly) and sent in the `apikey` header, not the URL.

CLI usage:
  python fmp_transcripts.py latest [--page N] [--limit N]
  python fmp_transcripts.py dates AAPL
  python fmp_transcripts.py symbols [--search apple]
  python fmp_transcripts.py transcript AAPL 2024 4 [--out aapl_q4_2024.txt]
  python fmp_transcripts.py most-recent AAPL [--out file.txt]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

BASE_URL = "https://financialmodelingprep.com/stable"


class FMPError(Exception):
    """Raised for HTTP errors or error payloads returned by FMP."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Transcript:
    symbol: str
    year: int
    quarter: int
    date: str
    content: str

    @classmethod
    def from_api(cls, row: dict[str, Any]) -> "Transcript":
        # FMP returns `period` as "Q1".."Q4"
        period = str(row.get("period", "")).upper().lstrip("Q")
        return cls(
            symbol=row.get("symbol", ""),
            year=int(row.get("year") or row.get("fiscalYear") or 0),
            quarter=int(period) if period.isdigit() else 0,
            date=row.get("date", ""),
            content=row.get("content", ""),
        )

    def speaker_turns(self) -> list[tuple[str, str]]:
        """Split content into (speaker, text) turns. FMP formats lines as 'Speaker: text'."""
        turns: list[tuple[str, str]] = []
        for line in self.content.splitlines():
            line = line.strip()
            if not line:
                continue
            speaker, sep, text = line.partition(": ")
            if sep and len(speaker) <= 80:
                turns.append((speaker, text))
            elif turns:
                turns[-1] = (turns[-1][0], turns[-1][1] + "\n" + line)
            else:
                turns.append(("", line))
        return turns


class FMPTranscriptClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.api_key = api_key or os.environ.get("FMP_API_KEY")
        if not self.api_key:
            raise FMPError("No API key: set FMP_API_KEY or pass api_key=")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    # -- transport -------------------------------------------------------

    def _get(self, path: str, **params: Any) -> Any:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self.base_url}/{path}" + (f"?{query}" if query else "")
        req = urllib.request.Request(
            url, headers={"apikey": self.api_key, "Accept": "application/json"}
        )

        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                # Retry on rate limiting / transient server errors
                if e.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise FMPError(f"HTTP {e.code} for {path}: {body[:300]}", e.code) from None
            except urllib.error.URLError as e:
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise FMPError(f"Network error for {path}: {e.reason}") from None

        # FMP sometimes returns 200 with an error object
        if isinstance(data, dict) and ("Error Message" in data or "error" in data):
            raise FMPError(data.get("Error Message") or data.get("error"))
        return data

    # -- endpoints -------------------------------------------------------

    def latest(self, page: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        """Latest earnings call transcripts across all companies (metadata only)."""
        return self._get("earning-call-transcript-latest", page=page, limit=limit)

    def transcript(self, symbol: str, year: int, quarter: int) -> Transcript | None:
        """Full transcript for one fiscal year/quarter, or None if unavailable."""
        if quarter not in (1, 2, 3, 4):
            raise ValueError("quarter must be 1-4")
        rows = self._get(
            "earning-call-transcript", symbol=symbol.upper(), year=year, quarter=quarter
        )
        return Transcript.from_api(rows[0]) if rows else None

    def dates(self, symbol: str) -> list[dict[str, Any]]:
        """Available transcripts for a symbol: [{quarter, fiscalYear, date}, ...], newest first."""
        rows = self._get("earning-call-transcript-dates", symbol=symbol.upper())
        return sorted(
            rows, key=lambda r: (r.get("fiscalYear", 0), r.get("quarter", 0)), reverse=True
        )

    def symbols(self) -> list[dict[str, Any]]:
        """All symbols with transcripts: [{symbol, companyName, noOfTranscripts}, ...]."""
        return self._get("earnings-transcript-list")

    # -- helpers ---------------------------------------------------------

    def most_recent(self, symbol: str) -> Transcript | None:
        """Fetch the newest available transcript for a symbol."""
        for d in self.dates(symbol):
            t = self.transcript(symbol, int(d["fiscalYear"]), int(d["quarter"]))
            if t:
                return t
        return None


# -- CLI ---------------------------------------------------------------------


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _emit_transcript(t: Transcript | None, out: str | None) -> int:
    if not t:
        print("No transcript found.", file=sys.stderr)
        return 1
    header = f"{t.symbol} Q{t.quarter} {t.year} earnings call ({t.date})\n\n"
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(header + t.content)
        print(f"Wrote {len(t.content):,} chars to {out}")
    else:
        print(header + t.content)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="FMP Earnings Transcript API client")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("latest", help="latest transcripts across companies")
    s.add_argument("--page", type=int, default=0)
    s.add_argument("--limit", type=int, default=20)

    s = sub.add_parser("dates", help="available transcript dates for a symbol")
    s.add_argument("symbol")

    s = sub.add_parser("symbols", help="symbols with transcripts")
    s.add_argument("--search", help="filter by symbol or company name substring")

    s = sub.add_parser("transcript", help="full transcript for symbol/year/quarter")
    s.add_argument("symbol")
    s.add_argument("year", type=int)
    s.add_argument("quarter", type=int, choices=[1, 2, 3, 4])
    s.add_argument("--out", help="write to file instead of stdout")

    s = sub.add_parser("most-recent", help="newest transcript for a symbol")
    s.add_argument("symbol")
    s.add_argument("--out", help="write to file instead of stdout")

    args = p.parse_args(argv)
    try:
        client = FMPTranscriptClient()
        if args.cmd == "latest":
            _print_json(client.latest(page=args.page, limit=args.limit))
        elif args.cmd == "dates":
            _print_json(client.dates(args.symbol))
        elif args.cmd == "symbols":
            rows = client.symbols()
            if args.search:
                q = args.search.lower()
                rows = [
                    r for r in rows
                    if q in str(r.get("symbol", "")).lower()
                    or q in str(r.get("companyName", "")).lower()
                ]
            _print_json(rows)
        elif args.cmd == "transcript":
            return _emit_transcript(
                client.transcript(args.symbol, args.year, args.quarter), args.out
            )
        elif args.cmd == "most-recent":
            return _emit_transcript(client.most_recent(args.symbol), args.out)
    except FMPError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
