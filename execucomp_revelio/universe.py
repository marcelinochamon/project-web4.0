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


def _norm_cik(value):
    """Normalise a CIK to its integer string form (drops zero-padding)."""
    if not value:
        return None
    digits = value.strip().lstrip("0")
    return digits or "0" if value.strip().isdigit() else None


def _funda_lookups(cur):
    """Return (gvkeys, tic->gvkeys, cik->gvkeys, (gvkey,year)->(conm, sic))."""
    gvkeys, tic_map, cik_map, info = set(), {}, {}, {}
    for gvkey, fyear, tic, cik, conm, sic, sich in cur.execute(
            "SELECT gvkey, fyear, tic, cik, conm, sic, sich FROM compustat_funda"):
        gvkeys.add(gvkey)
        if tic:
            tic_map.setdefault(tic.strip().upper(), set()).add(gvkey)
        nc = _norm_cik(cik)
        if nc:
            cik_map.setdefault(nc, set()).add(gvkey)
        if fyear is not None:
            info[(gvkey, fyear)] = (conm, sich or sic)
    return gvkeys, tic_map, cik_map, info


def build_universe_from_list(conn, min_fyear, max_fyear, excluded_ranges):
    """Build ``universe_firm_year`` from ``constituents_list`` instead of idxcst.

    Resolves each constituent to a Compustat ``gvkey`` (preferring an explicit
    gvkey, then CIK, then ticker), then keeps the firm-years that exist in
    ``compustat_funda``, fall in the window, and pass the SIC filter. Returns
    ``(kept_rows, stats)`` where ``stats`` reports how rows resolved.
    """
    cur = conn.cursor()
    gvkeys, tic_map, cik_map, info = _funda_lookups(cur)

    rows = cur.execute(
        "SELECT ticker, company, cik, gvkey, index_name, from_year, thru_year "
        "FROM constituents_list").fetchall()

    stats = {"constituents": len(rows), "by_gvkey": 0, "by_cik": 0,
             "by_ticker": 0, "unresolved": 0, "ambiguous": 0}
    kept = {}  # (gvkey, year) -> [conm, sic_used, set(index labels)]

    for ticker, company, cik, gvkey, index_name, from_year, thru_year in rows:
        resolved, method = set(), None
        gk = (gvkey or "").strip()
        if gk and gk in gvkeys:
            resolved, method = {gk}, "by_gvkey"
        else:
            nc = _norm_cik(cik)
            if nc and nc in cik_map:
                resolved, method = cik_map[nc], "by_cik"
            elif ticker and ticker.strip().upper() in tic_map:
                resolved, method = tic_map[ticker.strip().upper()], "by_ticker"

        if not resolved:
            stats["unresolved"] += 1
            continue
        stats[method] += 1
        if len(resolved) > 1:
            stats["ambiguous"] += 1

        lo = max(from_year or min_fyear, min_fyear)
        hi = min(thru_year or max_fyear, max_fyear)
        label = index_name or method
        for g in resolved:
            for year in range(lo, hi + 1):
                meta = info.get((g, year))
                if meta is None:
                    continue  # no fundamentals that year -> can't place it
                conm, sic_used = meta
                if _sic_excluded(sic_used, excluded_ranges):
                    continue
                entry = kept.setdefault((g, year), [conm, sic_used, set()])
                entry[2].add(label)

    kept_rows = [(g, y, conm, sic_used, "+".join(sorted(labels)))
                 for (g, y), (conm, sic_used, labels) in sorted(kept.items())]

    cur.execute("DELETE FROM universe_firm_year;")
    cur.executemany(
        "INSERT INTO universe_firm_year (gvkey, year, conm, sic_used, index_member) "
        "VALUES (?, ?, ?, ?, ?);",
        kept_rows,
    )
    conn.commit()
    return kept_rows, stats


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
