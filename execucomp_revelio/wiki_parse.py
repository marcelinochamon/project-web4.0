"""Convert Wikipedia 'List of S&P 400/600 companies' pages into constituent data.

Wikipedia is *current* membership only (a survivorship-biased proxy for a
historical panel) and carries no gvkey -- but its tables give ticker, name, and
(for the S&P 600) CIK, plus a "past changes" log. This module reads either a
Safari ``.webarchive``, a saved ``.html``, or a plain-text dump of those pages
and emits:

* **constituents** -- ``ticker,company,cik,index_name`` (use with ``--constituents``)
* **changes**      -- ``date,year,action,ticker,company,index_name,reason`` from
  the "Selected/Recent changes" tables (added/removed events)

Examples::

    # current constituents (one or more pages) -> one CSV
    python -m execucomp_revelio.wiki_parse sp400.webarchive sp600.webarchive \\
        -o sp1000_constituents.csv

    # the index change log instead
    python -m execucomp_revelio.wiki_parse --kind changes \\
        sp400.webarchive sp600.webarchive -o sp1000_changes.csv

Note the change logs do not reach the early years of a 2009-2019 study (the S&P
400 log starts ~2012, the S&P 600 log ~2019), so they cannot fully reconstruct
historical membership -- use WRDS ``idxcst_his`` for that.
"""

import argparse
import csv
import plistlib
import re
import sys
from html.parser import HTMLParser

_REF = re.compile(r"\[\d+\]")          # footnote markers like [2]
_YEAR = re.compile(r"(19|20)\d{2}")
_DATE_RX = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},\s*(19|20)\d{2}", re.IGNORECASE)
_TICKER_RX = re.compile(r"^[A-Za-z0-9.\-]{1,8}$")


def _is_date(s):
    return bool(_DATE_RX.search(s or ""))


def _valid_ticker(t):
    t = (t or "").strip()
    return bool(_TICKER_RX.match(t))


# --- HTML table extraction --------------------------------------------------

class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self._t, self._row, self._cell, self._in = [], None, None, None, False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._t = []
            self.tables.append(self._t)
        elif tag == "tr" and self._t is not None:
            self._row = []
            self._t.append(self._row)
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._in = [], True
        elif tag == "br" and self._in:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in:
            text = _REF.sub("", re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._row.append(text)
            self._in, self._cell = False, None
        elif tag == "table":
            self._t = None

    def handle_data(self, data):
        if self._in:
            self._cell.append(data)


def _html_from(path):
    """Return page HTML from a .webarchive, .mhtml/.mht, .html, or text file."""
    if path.endswith(".webarchive"):
        with open(path, "rb") as f:
            pl = plistlib.load(f)
        return pl["WebMainResource"]["WebResourceData"].decode("utf-8", "replace")
    if path.endswith((".mhtml", ".mht")):
        # MIME archive: find the HTML part and let email decode its transfer
        # encoding (quoted-printable / base64), which removes '=' soft breaks.
        import email
        with open(path, "rb") as f:
            msg = email.message_from_binary_file(f)
        parts = [p for p in msg.walk() if p.get_content_type() == "text/html"]
        if parts:
            biggest = max(parts, key=lambda p: len(p.get_payload(decode=True) or b""))
            return (biggest.get_payload(decode=True) or b"").decode("utf-8", "replace")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _tables(html):
    p = _TableParser()
    p.feed(html)
    return p.tables


def _index_label(path, html):
    blob = (path + " " + html[:2000]).lower()
    return "SP600SmallCap" if "600" in blob else "SP400MidCap"


# --- Row extractors ---------------------------------------------------------

def constituents_from_tables(tables, index_name):
    rows = []
    for t in tables:
        if not t or t[0][:2] != ["Symbol", "Security"]:
            continue
        has_cik = "CIK" in t[0]
        for r in t[1:]:
            if len(r) < 2 or not r[0]:
                continue
            cik = r[6] if has_cik and len(r) > 6 else ""
            rows.append({"ticker": r[0], "company": r[1], "cik": cik,
                         "index_name": index_name})
        break
    return rows


def changes_from_tables(tables, index_name):
    events = []
    for t in tables:
        if not t or t[0] != ["Date", "Added", "Removed", "Reason"]:
            continue
        # The Date (and often Reason) cells use rowspan to group several changes
        # under one date, so continuation rows arrive with 4 or 5 cells instead
        # of 6. Carry the last seen date/reason down to reconstruct them.
        last_date, last_reason = None, None
        for r in t[1:]:
            if not r or r[:2] == ["Ticker", "Security"]:
                continue
            if len(r) >= 6:
                date, add_t, add_s, rem_t, rem_s, reason = r[0], r[1], r[2], r[3], r[4], r[5]
            elif len(r) == 5:
                if _is_date(r[0]):          # date present, reason rowspanned
                    date, add_t, add_s, rem_t, rem_s, reason = r[0], r[1], r[2], r[3], r[4], last_reason
                else:                        # date rowspanned, reason present
                    date, add_t, add_s, rem_t, rem_s, reason = last_date, r[0], r[1], r[2], r[3], r[4]
            elif len(r) == 4:               # both date and reason rowspanned
                date, add_t, add_s, rem_t, rem_s, reason = last_date, r[0], r[1], r[2], r[3], last_reason
            else:
                continue
            if _is_date(date):
                last_date = date
            if reason:
                last_reason = reason
            if not _is_date(date):
                continue
            year = int(_YEAR.search(date).group())
            if _valid_ticker(add_t):
                events.append({"date": date, "year": year, "action": "added",
                               "ticker": add_t.strip(), "company": add_s,
                               "index_name": index_name, "reason": reason or ""})
            if _valid_ticker(rem_t):
                events.append({"date": date, "year": year, "action": "removed",
                               "ticker": rem_t.strip(), "company": rem_s,
                               "index_name": index_name, "reason": reason or ""})
        break
    return events


# --- Plain-text dump fallback (kept for copy/paste input) -------------------

_IGNORE_EXACT = {
    "article talk", "language watch edit", "watch", "edit", "language",
    "contents", "see also", "references", "related articles", "symbol",
    "security", "gics sector", "gics sub-industry", "headquarters location",
    "sec filings", "cik", "home", "random", "nearby", "log in", "settings",
    "donate now", "about wikipedia", "disclaimers", "install",
}
_IGNORE_PREFIX = (
    "last edited", "list of s&p", "the s&p", "below is", "stocks here",
    "these index", "the companies listed", "recent and announced",
    "selected past", "did you know", "donate", "if wikipedia", "privacy policy",
    "page was rendered", "content is available", "•", "s&p 600 component",
    "s&p midcap 400 component", "s&p 500",
)
_LETTER_INDEX = re.compile(r"^[a-z]( [a-z])+$")
_DIGITS = re.compile(r"^\d{4,10}$")


def _skip(line_lc):
    if line_lc in _IGNORE_EXACT or _LETTER_INDEX.match(line_lc):
        return True
    return any(line_lc.startswith(p) for p in _IGNORE_PREFIX)


def parse_text(text):
    """Parse a plain-text paste of the pages into constituent dicts."""
    label = "SP400MidCap"
    fields, rows, pending_cik = [], [], False

    def emit(cik=None):
        if fields:
            rows.append({"ticker": fields[0],
                         "company": fields[1] if len(fields) > 1 else "",
                         "cik": cik or "", "index_name": label})
        fields.clear()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("list of s&p 600"):
            label = "SP600SmallCap"
            fields.clear()
            continue
        if pending_cik and _DIGITS.match(line):
            emit(cik=line)
            pending_cik = False
            continue
        if low == "reports":
            emit()
            continue
        if low == "view":
            pending_cik = True
            continue
        if _skip(low):
            continue
        fields.append(line)
    return rows


# --- File-level convenience + CLI ------------------------------------------

def parse_file(path, kind="constituents"):
    """Parse one page file into constituent or change dicts."""
    html = _html_from(path)
    tables = _tables(html)
    label = _index_label(path, html)
    if not tables:                      # plain-text dump
        return parse_text(html) if kind == "constituents" else []
    if kind == "changes":
        return changes_from_tables(tables, label)
    return constituents_from_tables(tables, label)


_FIELDS = {
    "constituents": ["ticker", "company", "cik", "index_name"],
    "changes": ["date", "year", "action", "ticker", "company", "index_name", "reason"],
}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("inputs", nargs="+", help="Page files (.webarchive/.html/.txt).")
    p.add_argument("--kind", choices=["constituents", "changes"],
                   default="constituents", help="What to extract (default: constituents).")
    p.add_argument("-o", "--output", default=None, help="Output CSV (default: stdout).")
    args = p.parse_args(argv)

    rows, seen = [], set()
    for path in args.inputs:
        for row in parse_file(path, args.kind):
            key = tuple(row.get(k) for k in ("ticker", "index_name", "date", "action"))
            if key in seen:              # de-dupe duplicate uploads
                continue
            seen.add(key)
            rows.append(row)

    out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        w = csv.DictWriter(out, fieldnames=_FIELDS[args.kind])
        w.writeheader()
        w.writerows(rows)
    finally:
        if args.output:
            out.close()
    sys.stderr.write(f"Wrote {len(rows)} {args.kind} rows\n")


if __name__ == "__main__":
    main()
