"""Reconstruct historical index membership by walking the change log backward.

Given the *current* constituent list and the dated add/remove change log (both
from ``wiki_parse``), this recovers who was a member at each past year-end:
start from today's members and, stepping back in time, undo each change -- a
company "added" on date D was *not* a member before D; one "removed" on D *was*
a member before D.

Reliability is bounded by how far the log reaches: a year-end snapshot is sound
only for years at or after the index's oldest logged change (the "floor year").
Earlier years are *not* emitted, and the gap is reported, because the log gives
no information before it begins. (For the S&P 600 the floor is ~2019, so most of
a 2009-2019 window is uncovered -- fill it from WRDS ``idxcst_his``.)

Output is a constituent CSV with ``from_year``/``thru_year`` spans, ready for
``build_database --constituents``.

CLI::

    python -m execucomp_revelio.reconstruct sp400.webarchive sp600.webarchive \\
        --min-year 2009 --max-year 2019 -o sp1000_reconstructed.csv
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, datetime

from . import wiki_parse


def _parse_date(text):
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _spans(years):
    """Turn a sorted list of years into contiguous (from, thru) ranges."""
    spans, start, prev = [], None, None
    for y in years:
        if start is None:
            start = prev = y
        elif y == prev + 1:
            prev = y
        else:
            spans.append((start, prev))
            start = prev = y
    if start is not None:
        spans.append((start, prev))
    return spans


def reconstruct(constituents, changes, min_year, max_year):
    """Return ``(rows, coverage)``.

    ``rows`` are ``{ticker, company, cik, index_name, from_year, thru_year}``
    dicts (one per contiguous membership span, per index). ``coverage`` maps
    each index to ``{floor_year, asof_year, covered_years, missing_years}``.
    """
    present = defaultdict(dict)            # index -> {ticker: (company, cik)}
    for c in constituents:
        present[c["index_name"]][c["ticker"]] = (
            c.get("company") or "", c.get("cik") or "")

    events_by_index = defaultdict(list)    # index -> [(date, action, ticker, company)]
    for ch in changes:
        d = _parse_date(ch.get("date", ""))
        if d is None:
            continue
        events_by_index[ch["index_name"]].append(
            (d, ch["action"], ch["ticker"], ch.get("company") or ""))

    rows, coverage = [], {}
    for index_name in sorted(set(present) | set(events_by_index)):
        events = events_by_index.get(index_name, [])
        if not events:
            coverage[index_name] = {"floor_year": None, "asof_year": None,
                                    "covered_years": [], "missing_years":
                                    list(range(min_year, max_year + 1)),
                                    "note": "no change log"}
            continue

        floor_year = min(e[0].year for e in events)
        asof_year = max(e[0].year for e in events)

        names = {t: c for t, (c, _) in present[index_name].items()}
        ciks = {t: k for t, (_, k) in present[index_name].items()}
        for _d, _a, t, c in events:
            names.setdefault(t, c)        # name historical-only firms from the log

        current = set(present[index_name])
        events_desc = sorted(events, key=lambda e: e[0], reverse=True)
        member_years = defaultdict(set)
        i = 0
        for year in range(asof_year, floor_year - 1, -1):
            year_end = date(year, 12, 31)
            while i < len(events_desc) and events_desc[i][0] > year_end:
                _d, action, ticker, _c = events_desc[i]
                if action == "added":
                    current.discard(ticker)   # not a member before it was added
                elif action == "removed":
                    current.add(ticker)       # was a member before it was removed
                i += 1
            if min_year <= year <= max_year:
                for ticker in current:
                    member_years[ticker].add(year)

        for ticker, years in member_years.items():
            for lo, hi in _spans(sorted(years)):
                rows.append({"ticker": ticker, "company": names.get(ticker, ""),
                             "cik": ciks.get(ticker, ""), "index_name": index_name,
                             "from_year": lo, "thru_year": hi})

        requested = set(range(min_year, max_year + 1))
        covered = sorted(y for y in requested if floor_year <= y <= asof_year)
        coverage[index_name] = {
            "floor_year": floor_year, "asof_year": asof_year,
            "covered_years": covered,
            "missing_years": sorted(requested - set(covered)),
        }

    rows.sort(key=lambda r: (r["index_name"], r["ticker"], r["from_year"]))
    return rows, coverage


def format_coverage(coverage, min_year, max_year):
    lines = [f"Reconstruction coverage for {min_year}-{max_year}:"]
    for index_name, c in sorted(coverage.items()):
        if c["floor_year"] is None:
            lines.append(f"  {index_name}: no change log -> not reconstructable")
            continue
        cov = c["covered_years"]
        miss = c["missing_years"]
        cov_str = f"{cov[0]}-{cov[-1]}" if cov else "none"
        miss_str = (", ".join(map(str, miss)) if miss else "none")
        lines.append(
            f"  {index_name}: log floor {c['floor_year']} -> covered {cov_str}; "
            f"MISSING {miss_str}")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("inputs", nargs="+", help="Wikipedia page files (.webarchive/.html/.txt).")
    p.add_argument("--min-year", type=int, default=2009)
    p.add_argument("--max-year", type=int, default=2019)
    p.add_argument("-o", "--output", default=None, help="Output CSV (default: stdout).")
    args = p.parse_args(argv)

    constituents, changes, seen = [], [], set()
    for path in args.inputs:
        for row in wiki_parse.parse_file(path, "constituents"):
            key = (row["ticker"], row["index_name"])
            if key not in seen:
                seen.add(key)
                constituents.append(row)
        changes.extend(wiki_parse.parse_file(path, "changes"))

    # De-dupe identical change events across repeated uploads.
    uniq, ckeys = [], set()
    for ch in changes:
        k = (ch["date"], ch["action"], ch["ticker"], ch["index_name"])
        if k not in ckeys:
            ckeys.add(k)
            uniq.append(ch)

    rows, coverage = reconstruct(constituents, uniq, args.min_year, args.max_year)

    out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        w = csv.DictWriter(out, fieldnames=["ticker", "company", "cik",
                                            "index_name", "from_year", "thru_year"])
        w.writeheader()
        w.writerows(rows)
    finally:
        if args.output:
            out.close()
    sys.stderr.write(f"Wrote {len(rows)} membership-span rows\n")
    sys.stderr.write(format_coverage(coverage, args.min_year, args.max_year) + "\n")


if __name__ == "__main__":
    main()
