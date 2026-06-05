"""Survivorship-free mid/small-cap universe from CRSP (market-cap proxy).

Why this exists
---------------
``wrds_extract.universe`` builds the firm universe from Compustat
``idxcst_his`` (S&P MidCap 400 + SmallCap 600 membership). On many WRDS
licences that table is a **current snapshot**: it keeps only each firm's
*current* membership spell, with no ``thru`` (exit) dates -- so firms that
were dropped from the index (acquisitions, bankruptcies, graduations to
large-cap) silently vanish. Building a historical sample from it bakes in
survivorship bias; measured on this account the gap was ~30-36% of names
even over a 2021-2025 window.

This module sidesteps index membership entirely. It reconstructs the
"S&P 1000" idea -- mid- plus small-cap U.S. common stocks -- directly from
CRSP by ranking on market equity each June and keeping a fixed size band
(ranks 501-1500 by default: everything below the top 500, i.e. the
mid+small-cap region). Because CRSP retains every security that ever traded
and carries delisting returns, the resulting universe is survivorship-free:
firms that later died are present, and their final (delisting) return is
applied rather than dropped.

What it produces
----------------
Two CSVs in ``--outdir`` (gvkey zero-padded to 6 chars to line up with the
rest of ``execucomp_revelio``):

* ``crsp_mktcap_universe.csv`` -- one row per (formation June, firm):
  ``form_year, form_date, permno, gvkey, me, me_rank``.
* ``crsp_mktcap_returns.csv`` -- the held monthly panel (each June band held
  Jul..Jun): ``form_year, permno, gvkey, month, ret, dlret, retadj``.

Collapse either to ``gvkey`` x ``year`` to merge with Compustat/Execucomp.

Notes
-----
* Eligibility: CRSP share codes 10/11 (ordinary common shares) on NYSE/AMEX/
  Nasdaq (exchange codes 1/2/3).
* Ranking is across all eligible stocks by default ("the 1000 largest U.S.
  common stocks below the top 500"); pass ``--nyse-breaks`` for Fama-French
  style NYSE-only breakpoints applied to every stock.
* The held window naturally truncates at the latest CRSP date your licence
  carries (e.g. a 2024-12 monthly vintage caps the final holding period).

Run::

    pip install wrds pandas
    python -m execucomp_revelio.crsp_universe --username YOUR_WRDS_ID \\
        --start-year 2020 --end-year 2024 --outdir ./wrds_csv

All queries are plain ``db.raw_sql`` and avoid literal ``%`` (psycopg2 reads
it as a bind parameter under SQLAlchemy 2).
"""

import argparse
import os
import sys


TABLES = {
    "msf": "crsp.msf",
    "msenames": "crsp.msenames",
    "msedelist": "crsp.msedelist",
    "lnkhist": "crsp.ccmxpf_lnkhist",
}

SHARE_CODES = (10, 11)          # ordinary common shares
EXCHANGE_CODES = (1, 2, 3)      # NYSE / AMEX / Nasdaq
DEFAULT_BAND = (501, 1500)      # mid + small cap: below the top 500


def _chunks(seq, n=900):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _int_list(values):
    """Comma-joined integer literals for a SQL IN (...) clause."""
    return ",".join(str(int(v)) for v in values)


def _norm_gvkey(series):
    """Compustat-style 6-char zero-padded gvkey (so downstream joins line up)."""
    s = series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    return s.where(s.isin(["", "nan", "None", "<NA>"]), s.str.zfill(6))


# --- Step 1: June market-equity universe -----------------------------------

def build_universe(db, start_year, end_year, band, nyse_breaks):
    """Rank eligible CRSP commons by June market equity; keep the size band.

    Returns a DataFrame: form_year, form_date, permno, me, me_rank.
    """
    import pandas as pd

    lo, hi = band
    msf = db.raw_sql(f"""
        SELECT a.permno, a.date, a.prc, a.shrout, b.exchcd
        FROM {TABLES['msf']} a
        JOIN {TABLES['msenames']} b
          ON a.permno = b.permno
         AND a.date BETWEEN b.namedt AND b.nameendt
        WHERE EXTRACT(MONTH FROM a.date) = 6
          AND EXTRACT(YEAR  FROM a.date) BETWEEN {start_year} AND {end_year}
          AND b.shrcd IN ({_int_list(SHARE_CODES)})
          AND b.exchcd IN ({_int_list(EXCHANGE_CODES)})
    """)

    msf["me"] = msf["prc"].abs() * msf["shrout"]          # market equity ($000s)
    msf = msf[msf["me"] > 0].dropna(subset=["me"]).copy()
    msf["form_year"] = pd.to_datetime(msf["date"]).dt.year

    kept = []
    for year, grp in msf.groupby("form_year"):
        if nyse_breaks:
            # Fama-French style: cutoffs from NYSE firms, applied to everyone.
            nyse = grp[grp["exchcd"] == 1]["me"].sort_values(ascending=False)
            if len(nyse) < hi:
                print(f"  [{year}] only {len(nyse)} NYSE firms; "
                      f"band {hi} exceeds NYSE breakpoints -- skipping year")
                continue
            hi_cut = nyse.iloc[lo - 1]      # ME of the (lo-1)th NYSE firm (top edge)
            lo_cut = nyse.iloc[hi - 1]      # ME of the hi-th NYSE firm (bottom edge)
            band_grp = grp[(grp["me"] <= hi_cut) & (grp["me"] >= lo_cut)].copy()
            band_grp["me_rank"] = band_grp["me"].rank(ascending=False, method="first")
        else:
            grp = grp.copy()
            grp["me_rank"] = grp["me"].rank(ascending=False, method="first")
            band_grp = grp[(grp["me_rank"] >= lo) & (grp["me_rank"] <= hi)].copy()
        kept.append(band_grp)

    univ = pd.concat(kept, ignore_index=True)
    univ = univ.rename(columns={"date": "form_date"})
    return univ[["form_year", "form_date", "permno", "me", "me_rank"]]


# --- Step 2: delisting-adjusted monthly returns ----------------------------

def build_returns(db, univ, start_year, end_year):
    """Held monthly panel: each June band held Jul..Jun, delisting-adjusted.

    Returns a DataFrame: form_year, permno, month, ret, dlret, retadj.
    """
    import numpy as np
    import pandas as pd

    permnos = sorted(int(p) for p in univ["permno"].unique())
    lo_date = f"{start_year}-07-01"
    hi_date = f"{end_year + 1}-06-30"

    ret_frames, dl_frames = [], []
    for chunk in _chunks(permnos):
        ret_frames.append(db.raw_sql(f"""
            SELECT permno, date, ret FROM {TABLES['msf']}
            WHERE date BETWEEN '{lo_date}' AND '{hi_date}'
              AND permno IN ({_int_list(chunk)})
        """))
        dl_frames.append(db.raw_sql(f"""
            SELECT permno, dlstdt, dlret FROM {TABLES['msedelist']}
            WHERE dlstdt BETWEEN '{lo_date}' AND '{hi_date}'
              AND permno IN ({_int_list(chunk)})
        """))
    ret = pd.concat(ret_frames, ignore_index=True)
    dl = pd.concat(dl_frames, ignore_index=True)

    ret["date"] = pd.to_datetime(ret["date"])
    ret["ym"] = ret["date"].dt.to_period("M")
    # Formation June that "owns" each held month: Jul..Dec -> this year,
    # Jan..Jun -> previous year.
    ret["form_year"] = ret["date"].dt.year - (ret["date"].dt.month <= 6).astype(int)

    mem = univ[["permno", "form_year"]].drop_duplicates()
    panel = ret.merge(mem, on=["permno", "form_year"], how="inner")

    if len(dl):
        dl["ym"] = pd.to_datetime(dl["dlstdt"]).dt.to_period("M")
        panel = panel.merge(dl[["permno", "ym", "dlret"]], on=["permno", "ym"],
                            how="left")
    else:
        panel["dlret"] = np.nan

    panel["ret"] = pd.to_numeric(panel["ret"], errors="coerce")
    panel["dlret"] = pd.to_numeric(panel["dlret"], errors="coerce")
    r, d = panel["ret"], panel["dlret"]
    panel["retadj"] = np.where(d.isna(), r,
                       np.where(r.isna(), d, (1 + r) * (1 + d) - 1))

    panel["month"] = panel["date"].dt.strftime("%Y-%m-%d")
    return panel[["form_year", "permno", "month", "ret", "dlret", "retadj"]]


# --- Step 3: permno -> gvkey link ------------------------------------------

def link_gvkey(db, univ):
    """Attach Compustat gvkey to each (permno, formation) via the CCM link.

    Uses the standard research link (linktype LU/LC, primary LINKPRIM P/C) and
    requires the formation date to fall inside the link's validity window.
    Returns ``univ`` with a ``gvkey`` column added.
    """
    import pandas as pd

    permnos = sorted(int(p) for p in univ["permno"].unique())
    frames = []
    for chunk in _chunks(permnos):
        frames.append(db.raw_sql(f"""
            SELECT gvkey, lpermno AS permno, linkdt, linkenddt
            FROM {TABLES['lnkhist']}
            WHERE linktype IN ('LU','LC') AND linkprim IN ('P','C')
              AND lpermno IN ({_int_list(chunk)})
        """))
    link = pd.concat(frames, ignore_index=True)
    link["linkdt"] = pd.to_datetime(link["linkdt"])
    link["linkenddt"] = pd.to_datetime(link["linkenddt"]).fillna(
        pd.Timestamp("2100-01-01"))

    u = univ.copy()
    u["form_date"] = pd.to_datetime(u["form_date"])
    u = u.merge(link, on="permno", how="left")
    in_window = (u["form_date"] >= u["linkdt"]) & (u["form_date"] <= u["linkenddt"])
    u = u[in_window | u["gvkey"].isna()]
    u = u.sort_values("gvkey").drop_duplicates(subset=["permno", "form_year"],
                                               keep="first")
    u["gvkey"] = _norm_gvkey(u["gvkey"])
    return u.drop(columns=["linkdt", "linkenddt"])


# --- Orchestration ---------------------------------------------------------

def run(username, outdir, start_year, end_year, band, nyse_breaks):
    import wrds

    os.makedirs(outdir, exist_ok=True)
    db = wrds.Connection(wrds_username=username)
    try:
        univ = build_universe(db, start_year, end_year, band, nyse_breaks)
        counts = univ.groupby("form_year").size()
        print(f"Universe (ranks {band[0]}-{band[1]}, "
              f"{'NYSE breaks' if nyse_breaks else 'all-stock ranks'}):")
        for year, n in counts.items():
            print(f"  {year}: {n} firms")
        print(f"  firm-formations: {len(univ)} | "
              f"unique permnos: {univ['permno'].nunique()} "
              f"(survivorship-free: > per-year count)")

        univ = link_gvkey(db, univ)
        matched = univ["gvkey"].ne("").sum()
        print(f"  gvkey linked: {matched}/{len(univ)} "
              f"({matched / len(univ):.1%}) | "
              f"unique gvkeys: {univ.loc[univ['gvkey'].ne(''), 'gvkey'].nunique()}")

        panel = build_returns(db, univ, start_year, end_year)
        # carry gvkey onto the return panel
        gv = univ[["permno", "form_year", "gvkey"]].drop_duplicates()
        panel = panel.merge(gv, on=["permno", "form_year"], how="left")
        print(f"  return panel: {len(panel)} permno-months "
              f"({panel['month'].min()} .. {panel['month'].max()}) | "
              f"delisting returns applied: {panel['dlret'].notna().sum()}")

        upath = os.path.join(outdir, "crsp_mktcap_universe.csv")
        univ[["form_year", "form_date", "permno", "gvkey", "me", "me_rank"]] \
            .assign(form_date=lambda d: d["form_date"].dt.strftime("%Y-%m-%d")) \
            .to_csv(upath, index=False)
        rpath = os.path.join(outdir, "crsp_mktcap_returns.csv")
        panel[["form_year", "permno", "gvkey", "month", "ret", "dlret", "retadj"]] \
            .to_csv(rpath, index=False)
        print(f"\nWrote:\n  {upath} ({len(univ)} rows)\n  {rpath} ({len(panel)} rows)")
    finally:
        db.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--username", required=True)
    p.add_argument("--outdir", default="./wrds_csv")
    p.add_argument("--start-year", type=int, default=2020,
                   help="First June formation year (default 2020).")
    p.add_argument("--end-year", type=int, default=2024,
                   help="Last June formation year (default 2024).")
    p.add_argument("--band-lo", type=int, default=DEFAULT_BAND[0],
                   help="Top edge of the size band by ME rank (default 501).")
    p.add_argument("--band-hi", type=int, default=DEFAULT_BAND[1],
                   help="Bottom edge of the size band by ME rank (default 1500).")
    p.add_argument("--nyse-breaks", action="store_true",
                   help="Use NYSE-only breakpoints (Fama-French style) instead "
                        "of ranking across all eligible stocks.")
    args = p.parse_args(argv)
    try:
        run(args.username, args.outdir, args.start_year, args.end_year,
            (args.band_lo, args.band_hi), args.nyse_breaks)
    except ImportError:
        sys.exit("The 'wrds' package is required: pip install wrds pandas")


if __name__ == "__main__":
    main()
