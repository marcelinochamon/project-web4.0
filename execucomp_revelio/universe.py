"""Build the firm-year universe: S&P 1000, in study window, ex excluded SIC.

The universe is the spine onto which Execucomp and Revelio are merged. A
Compustat firm-year (``gvkey``, ``fyear``) is kept when all three hold:

1. **Window**   - ``MIN_FYEAR <= fyear <= MAX_FYEAR``.
2. **S&P 1000** - the firm was a constituent of one of the configured S&P index
   codes (MidCap 400 + SmallCap 600) at some point during that fiscal year,
   per ``compustat_index_constituents`` (idxcst_his) date ranges.
3. **Industry** - its SIC (historical ``sich`` preferred, else header ``sic``)
   does not fall in any excluded range (financials & utilities by default).

Membership is evaluated on the fiscal *year* (calendar-year overlap of the
``from_date``/``thru_date`` window) rather than exact dates, which is robust to
the date formats WRDS exports use and to fiscal-year-end variation.
"""


def _year_of(date_text):
    """Extract the 4-digit year from a 'YYYY-...' date string, or None."""
    if not date_text:
        return None
    head = date_text.strip()[:4]
    return int(head) if head.isdigit() else None


def _sic_excluded(sic_text, excluded_ranges):
    if not sic_text:
        return False
    digits = sic_text.strip()[:4]
    if not digits.isdigit():
        return False
    code = int(digits)
    return any(lo <= code <= hi for lo, hi in excluded_ranges)


def _membership_by_year(index_rows, index_gvkeyx):
    """Map gvkey -> {year: set(gvkeyx)} for the configured index codes.

    A membership row contributes its index code to every calendar year its
    [from_date, thru_date] window spans. An open (NULL) ``thru_date`` is treated
    as current and extended to a far-future sentinel.
    """
    wanted = set(index_gvkeyx)
    membership = {}
    for gvkey, gvkeyx, _conm, _indexname, from_date, thru_date in index_rows:
        if gvkeyx not in wanted:
            continue
        start = _year_of(from_date) or 1900
        end = _year_of(thru_date) or 9999
        per_year = membership.setdefault(gvkey, {})
        for year in range(start, end + 1):
            per_year.setdefault(year, set()).add(gvkeyx)
    return membership


def build_universe(conn, index_gvkeyx, min_fyear, max_fyear, excluded_ranges):
    """Compute and load ``universe_firm_year``; return the list of kept rows."""
    cur = conn.cursor()

    index_rows = cur.execute(
        "SELECT gvkey, gvkeyx, conm, indexname, from_date, thru_date "
        "FROM compustat_index_constituents"
    ).fetchall()
    membership = _membership_by_year(index_rows, index_gvkeyx)

    funda_rows = cur.execute(
        "SELECT gvkey, fyear, conm, sic, sich FROM compustat_funda"
    ).fetchall()

    kept = []
    for gvkey, fyear, conm, sic, sich in funda_rows:
        if fyear is None or not (min_fyear <= fyear <= max_fyear):
            continue
        member_codes = membership.get(gvkey, {}).get(fyear)
        if not member_codes:
            continue
        sic_used = sich or sic
        if _sic_excluded(sic_used, excluded_ranges):
            continue
        kept.append((gvkey, fyear, conm, sic_used, "+".join(sorted(member_codes))))

    cur.execute("DELETE FROM universe_firm_year;")
    cur.executemany(
        "INSERT INTO universe_firm_year (gvkey, year, conm, sic_used, index_member) "
        "VALUES (?, ?, ?, ?, ?);",
        kept,
    )
    conn.commit()
    return kept
