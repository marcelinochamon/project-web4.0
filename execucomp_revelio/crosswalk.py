"""Build the company crosswalk (gvkey <-> rcid).

Unlike the firm-level ``compustat_revelio`` module, here the link is *given*:
Revelio's company-mapping file carries ``gvkey`` directly, so the primary link
is a straight join on ``gvkey``. Ticker and CUSIP are only fallbacks for the
rare ``rcid`` whose mapping row lacks a ``gvkey``.

The relationship is intentionally many-to-many: a single Compustat ``gvkey`` can
correspond to several Revelio ``rcid`` entities (subsidiaries, rebrandings), and
we want positions at *any* of them when assembling an executive's tenure.
"""


def _clean(value):
    return (value or "").strip().upper() or None


def _cusip8(value):
    v = _clean(value)
    return v[:8] if v else None


def build_crosswalk(conn):
    """Compute and load ``company_crosswalk``; return the link tuples.

    Only ``gvkey`` values that actually appear in Compustat fundamentals are
    linked, so the crosswalk stays scoped to the study companies.
    """
    cur = conn.cursor()

    funda_gvkeys = {row[0] for row in
                    cur.execute("SELECT DISTINCT gvkey FROM compustat_funda")}

    # Indexes from the Compustat side for the fallbacks.
    tic_to_gvkeys, cusip_to_gvkeys = {}, {}
    for gvkey, tic, cusip in cur.execute(
            "SELECT DISTINCT gvkey, tic, cusip FROM compustat_funda"):
        t = _clean(tic)
        if t:
            tic_to_gvkeys.setdefault(t, set()).add(gvkey)
        c = _cusip8(cusip)
        if c:
            cusip_to_gvkeys.setdefault(c, set()).add(gvkey)

    mapping = cur.execute(
        "SELECT rcid, gvkey, ticker, cusip FROM revelio_company_mapping"
    ).fetchall()

    # (gvkey, rcid) -> (method, confidence); dict de-dupes repeated links.
    links = {}
    for rcid, gvkey, ticker, cusip in mapping:
        if not rcid:
            continue
        gk = _clean(gvkey)
        if gk and gk in funda_gvkeys:
            links[(gk, rcid)] = ("revelio_gvkey", 0.99)
            continue
        # Fallbacks only when Revelio gives no usable gvkey.
        t = _clean(ticker)
        if t and t in tic_to_gvkeys:
            for cand in tic_to_gvkeys[t]:
                links.setdefault((cand, rcid), ("ticker", 0.90))
            continue
        c = _cusip8(cusip)
        if c and c in cusip_to_gvkeys:
            for cand in cusip_to_gvkeys[c]:
                links.setdefault((cand, rcid), ("cusip", 0.92))

    rows = [(gvkey, rcid, method, conf)
            for (gvkey, rcid), (method, conf) in sorted(links.items())]

    cur.execute("DELETE FROM company_crosswalk;")
    cur.executemany(
        "INSERT INTO company_crosswalk (gvkey, rcid, match_method, match_confidence) "
        "VALUES (?, ?, ?, ?);",
        rows,
    )
    conn.commit()
    return rows
