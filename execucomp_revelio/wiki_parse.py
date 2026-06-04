"""Convert a Wikipedia 'List of S&P 400/600 companies' dump into a constituent CSV.

Wikipedia is *current* membership only (a survivorship-biased proxy for a
historical panel) and carries no gvkey -- but its tables do give ticker, name,
and (for the S&P 600) CIK, which the pipeline can resolve to gvkey. This parser
turns a copy/paste or saved dump of those pages into a clean CSV with columns
``ticker,company,cik,index_name`` for use with ``--constituents``.

Use it on the *downloaded* page text for full fidelity::

    python -m execucomp_revelio.wiki_parse sp1000_dump.txt -o sp1000_constituents.csv

The parser is delimiter-driven: an S&P 400 record ends at a ``reports`` line; an
S&P 600 record ends at the ``view`` line followed by a numeric CIK. Header and
boilerplate lines are ignored. It auto-switches the index label when it sees the
'List of S&P 600 companies' heading.
"""

import argparse
import csv
import re
import sys

# Lines that are never company fields (lower-cased, exact match).
_IGNORE_EXACT = {
    "article talk", "language watch edit", "watch", "edit", "language",
    "contents", "see also", "references", "related articles", "symbol",
    "security", "gics sector", "gics sub-industry", "headquarters location",
    "sec filings", "cik", "home", "random", "nearby", "log in", "settings",
    "donate now", "about wikipedia", "disclaimers", "install",
}
# Prefixes that mark boilerplate / prose lines to skip.
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
    """Parse dump text into a list of ``{ticker, company, cik, index_name}`` dicts."""
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
            label = "SP600SmallCap"  # switch when the second table starts
            fields.clear()
            continue
        if pending_cik and _DIGITS.match(line):
            emit(cik=line)
            pending_cik = False
            continue
        if low == "reports":         # S&P 400 record terminator
            emit()
            continue
        if low == "view":            # S&P 600: CIK comes on the next line
            pending_cik = True
            continue
        if _skip(low):
            continue
        fields.append(line)

    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("input", help="Path to the Wikipedia dump text file.")
    p.add_argument("-o", "--output", default=None,
                   help="Output CSV path (default: stdout).")
    args = p.parse_args(argv)

    with open(args.input, encoding="utf-8") as fh:
        rows = parse_text(fh.read())

    out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        writer = csv.DictWriter(out, fieldnames=["ticker", "company", "cik", "index_name"])
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if args.output:
            out.close()
    sys.stderr.write(f"Parsed {len(rows)} constituents\n")


if __name__ == "__main__":
    main()
