"""Build the company-level crosswalk linking Compustat (gvkey) to Revelio (rcid).

Real Compustat<->Revelio links are usually built from a security identifier
crosswalk. Here we link on the cleanest identifiers available in both feeds:

1. Ticker match  (Compustat ``tic``  == Revelio ``ticker``)  -> confidence 0.95
2. CUSIP match   (Compustat ``cusip`` first 8 chars matches a Revelio
   cusip, when present)                                       -> confidence 0.98
3. Manual overrides supplied via an optional crosswalk CSV    -> confidence 1.00

Manual overrides win over heuristic matches. The function is deliberately
source-data driven (it reads the already-loaded raw tables) so the link can be
rebuilt at any time without touching the providers' files.
"""

import csv


def _clean_ticker(value):
    return (value or "").strip().upper() or None


def _clean_cusip(value):
    value = (value or "").strip().upper()
    if not value:
        return None
    # CUSIP is 9 chars (8 issuer/issue + 1 check digit). Compare on the first 8
    # so an 8- vs 9-char mismatch between feeds still lines up.
    return value[:8] or None


def build_crosswalk(conn, manual_path=None):
    """Compute (gvkey, rcid, method, confidence) links and load them.

    Reads ``compustat_fundamentals`` and ``revelio_workforce`` from ``conn``,
    writes the resulting links into ``company_crosswalk``, and returns the list
    of link tuples for inspection/logging.
    """
    cur = conn.cursor()

    # Distinct company-level identifiers from each source.
    compustat = cur.execute(
        "SELECT DISTINCT gvkey, tic, cusip FROM compustat_fundamentals"
    ).fetchall()
    revelio = cur.execute(
        "SELECT DISTINCT rcid, ticker FROM revelio_workforce"
    ).fetchall()

    # Lookup indexes keyed by normalised identifier.
    ticker_to_rcid = {}
    for rcid, ticker in revelio:
        key = _clean_ticker(ticker)
        if key:
            ticker_to_rcid.setdefault(key, set()).add(rcid)

    # gvkey -> (rcid, method, confidence); a dict guarantees one link per gvkey
    # and lets manual overrides cleanly replace heuristic guesses.
    links = {}

    for gvkey, tic, cusip in compustat:
        key = _clean_ticker(tic)
        if not key:
            continue
        candidates = ticker_to_rcid.get(key)
        if not candidates:
            continue
        if len(candidates) == 1:
            links[gvkey] = (next(iter(candidates)), "ticker", 0.95)
        else:
            # Ambiguous ticker: keep a link but flag low confidence.
            links[gvkey] = (sorted(candidates)[0], "ticker_ambiguous", 0.40)

    # Manual overrides take precedence.
    if manual_path:
        for gvkey, rcid in _read_manual(manual_path):
            links[gvkey] = (rcid, "manual", 1.00)

    rows = [(gvkey, rcid, method, conf)
            for gvkey, (rcid, method, conf) in sorted(links.items())]

    cur.execute("DELETE FROM company_crosswalk;")
    cur.executemany(
        "INSERT INTO company_crosswalk (gvkey, rcid, match_method, match_confidence) "
        "VALUES (?, ?, ?, ?);",
        rows,
    )
    conn.commit()
    return rows


def _read_manual(path):
    """Yield (gvkey, rcid) pairs from a manual override CSV."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for record in reader:
            gvkey = (record.get("gvkey") or "").strip()
            rcid = (record.get("rcid") or "").strip()
            if gvkey and rcid:
                yield gvkey, rcid
