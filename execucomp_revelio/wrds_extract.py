"""Extract the six pipeline inputs directly from WRDS.

This runs on **your** WRDS access (it needs your credentials + Duo 2FA and
network access to WRDS, neither of which exist in a sandbox). It uses the
official ``wrds`` Python package and writes CSVs whose headers match exactly
what ``execucomp_revelio`` expects, so the flow is simply::

    pip install wrds
    python -m execucomp_revelio.wrds_extract --username YOUR_WRDS_ID --outdir ./wrds_csv
    python -m execucomp_revelio \
        --funda           ./wrds_csv/compustat_funda.csv \
        --index           ./wrds_csv/compustat_idxcst_his.csv \
        --execucomp       ./wrds_csv/execucomp_anncomp.csv \
        --individual      ./wrds_csv/revelio_individual.csv \
        --positions       ./wrds_csv/revelio_positions.csv \
        --company-mapping ./wrds_csv/revelio_company_mapping.csv \
        --export-dir      ./out

Run ``--list`` FIRST to confirm the library/table/column names in your WRDS
vintage (schemas drift over time); adjust the TABLES/COLUMNS config below if
``--list`` shows different names. Everything here is plain SQL via
``db.raw_sql`` so you can also paste the queries into the WRDS web query tool
and download each result as CSV.
"""

import argparse
import os
import sys

# --- WRDS schema configuration (confirm with --list, then edit if needed) ---
#
# Library/table names as they appear in WRDS PostgreSQL. These match the common
# 2023+ layout; older accounts may differ (e.g. execucomp as ``execcomp``).
TABLES = {
    "funda": "comp.funda",
    "company": "comp.company",
    "idxcst_his": "comp.idxcst_his",
    "idx_index": "comp.idx_index",
    "anncomp": "comp_execucomp.anncomp",
    "rev_individual": "revelio.individual_user",
    "rev_positions": "revelio.individual_positions",
    "rev_company": "revelio.company_mapping",
}

# Compustat gvkeyx codes for the two S&P 1000 sub-indexes. Confirm via --list
# (prints idx_index rows matching 'midcap 400' / 'smallcap 600').
DEFAULT_MIDCAP_GVKEYX = "000400"
DEFAULT_SMALLCAP_GVKEYX = "000600"


def _chunks(seq, n=900):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _in_list(values):
    """SQL-safe quoted IN-list from string values."""
    return ",".join("'" + str(v).replace("'", "''") + "'" for v in values)


# --- Discovery -------------------------------------------------------------

def list_schema(db):
    """Print candidate libraries/tables/columns so names can be confirmed."""
    for lib in ("comp", "comp_execucomp", "execcomp", "revelio"):
        try:
            tables = db.list_tables(library=lib)
        except Exception as exc:                       # noqa: BLE001
            print(f"[{lib}] not accessible: {exc}")
            continue
        print(f"\n[{lib}] {len(tables)} tables")
        for t in tables:
            if any(k in t for k in ("funda", "company", "idx", "anncomp",
                                    "individual", "position", "mapping", "user")):
                print(f"   - {t}")
    # Index code lookup for the S&P 1000 sub-indexes.
    try:
        idx = db.raw_sql(
            f"SELECT gvkeyx, conm FROM {TABLES['idx_index']} "
            "WHERE conm ILIKE '%midcap 400%' OR conm ILIKE '%smallcap 600%' "
            "OR conm ILIKE '%s&p 1000%'")
        print("\nIndex gvkeyx candidates:\n", idx.to_string(index=False))
    except Exception as exc:                           # noqa: BLE001
        print("idx_index lookup failed:", exc)


# --- Extraction steps ------------------------------------------------------

def universe_gvkeys(db, midcap, smallcap, min_year, max_year):
    """Return (idxcst_df, sorted gvkey list) for S&P 1000 in the window."""
    sql = f"""
        SELECT gvkey, gvkeyx, "from" AS from_date, thru AS thru_date
        FROM {TABLES['idxcst_his']}
        WHERE gvkeyx IN ('{midcap}','{smallcap}')
          AND ("from" IS NULL OR EXTRACT(YEAR FROM "from") <= {max_year})
          AND (thru   IS NULL OR EXTRACT(YEAR FROM thru)   >= {min_year})
    """
    df = db.raw_sql(sql)
    df["indexname"] = df["gvkeyx"].map(
        {midcap: "S&P MidCap 400", smallcap: "S&P SmallCap 600"})
    df["conm"] = None
    df = df[["gvkey", "gvkeyx", "conm", "indexname", "from_date", "thru_date"]]
    return df, sorted(df["gvkey"].astype(str).unique())


def extract_funda(db, gvkeys, min_year, max_year):
    frames = []
    for chunk in _chunks(gvkeys):
        sql = f"""
            SELECT f.gvkey, f.fyear, f.datadate, f.tic, f.cusip, c.cik, f.conm,
                   f.sale, f.at, f.ni, f.ceq, f.dltt, f.capx, f.xrd, f.emp,
                   COALESCE(f.naicsh::text, c.naics) AS naics, c.sic, f.sich
            FROM {TABLES['funda']} f
            LEFT JOIN {TABLES['company']} c ON c.gvkey = f.gvkey
            WHERE f.indfmt='INDL' AND f.datafmt='STD' AND f.popsrc='D'
              AND f.consol='C'
              AND f.fyear BETWEEN {min_year} AND {max_year}
              AND f.gvkey IN ({_in_list(chunk)})
        """
        frames.append(db.raw_sql(sql))
    return _concat(frames)


def extract_anncomp(db, gvkeys, min_year, max_year):
    frames = []
    for chunk in _chunks(gvkeys):
        sql = f"""
            SELECT gvkey, year, execid, co_per_rol, exec_fullname,
                   exec_fname, exec_mname, exec_lname, coname, title,
                   ceoann, cfoann, joined_co, leftofc AS leftco,
                   salary, bonus, tdc1, tdc2, age, gender
            FROM {TABLES['anncomp']}
            WHERE year BETWEEN {min_year} AND {max_year}
              AND gvkey IN ({_in_list(chunk)})
        """
        frames.append(db.raw_sql(sql))
    return _concat(frames)


def extract_company_mapping(db, gvkeys):
    frames = []
    for chunk in _chunks(gvkeys):
        sql = f"""
            SELECT rcid, company, ticker, cusip, isin, gvkey, lei, naics, sic
            FROM {TABLES['rev_company']}
            WHERE gvkey IN ({_in_list(chunk)})
        """
        frames.append(db.raw_sql(sql))
    return _concat(frames)


def extract_positions_and_users(db, rcids):
    """Two-stage: positions at focal companies -> their users -> ALL positions.

    This yields each matched person's *complete* work history (every employer),
    not just the focal-firm spell.
    """
    # Stage 1: user_ids who held a position at a focal rcid.
    user_frames = []
    for chunk in _chunks(rcids):
        user_frames.append(db.raw_sql(
            f"SELECT DISTINCT user_id FROM {TABLES['rev_positions']} "
            f"WHERE rcid IN ({_in_list(chunk)})"))
    users = sorted(_concat(user_frames)["user_id"].astype(str).unique())

    # Stage 2: ALL positions for those users + their individual records.
    pos_cols = ("position_id, user_id, rcid, company, position_number, "
                "role_raw, role_k150, role_k1500, seniority, salary, "
                "startdate, enddate, location")
    pos_frames, ind_frames = [], []
    for chunk in _chunks(users):
        pos_frames.append(db.raw_sql(
            f"SELECT {pos_cols} FROM {TABLES['rev_positions']} "
            f"WHERE user_id IN ({_in_list(chunk)})"))
        ind_frames.append(db.raw_sql(
            "SELECT user_id, fullname, firstname, lastname, gender, ethnicity "
            f"FROM {TABLES['rev_individual']} WHERE user_id IN ({_in_list(chunk)})"))
    return _concat(pos_frames), _concat(ind_frames), len(users)


def _concat(frames):
    import pandas as pd
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# --- Orchestration ---------------------------------------------------------

def run(username, outdir, min_year, max_year, midcap, smallcap, do_list):
    import wrds
    os.makedirs(outdir, exist_ok=True)
    db = wrds.Connection(wrds_username=username)
    try:
        if do_list:
            list_schema(db)
            return

        idxcst, gvkeys = universe_gvkeys(db, midcap, smallcap, min_year, max_year)
        print(f"S&P 1000 universe: {len(gvkeys)} distinct gvkeys")
        idxcst.to_csv(os.path.join(outdir, "compustat_idxcst_his.csv"), index=False)

        funda = extract_funda(db, gvkeys, min_year, max_year)
        funda.to_csv(os.path.join(outdir, "compustat_funda.csv"), index=False)
        print(f"funda: {len(funda)} firm-years")

        anncomp = extract_anncomp(db, gvkeys, min_year, max_year)
        anncomp.to_csv(os.path.join(outdir, "execucomp_anncomp.csv"), index=False)
        print(f"anncomp: {len(anncomp)} exec-years")

        mapping = extract_company_mapping(db, gvkeys)
        mapping.to_csv(os.path.join(outdir, "revelio_company_mapping.csv"), index=False)
        rcids = sorted(mapping["rcid"].dropna().astype(str).unique())
        print(f"company mapping: {len(mapping)} rows, {len(rcids)} rcids")

        positions, individuals, n_users = extract_positions_and_users(db, rcids)
        positions.to_csv(os.path.join(outdir, "revelio_positions.csv"), index=False)
        individuals.to_csv(os.path.join(outdir, "revelio_individual.csv"), index=False)
        print(f"revelio: {n_users} users, {len(positions)} positions")
        print(f"\nDone. CSVs in {outdir}/ — now run `python -m execucomp_revelio`.")
    finally:
        db.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--username", required=True, help="Your WRDS username.")
    p.add_argument("--outdir", default="./wrds_csv", help="Output directory for CSVs.")
    p.add_argument("--min-year", type=int, default=2009)
    p.add_argument("--max-year", type=int, default=2019)
    p.add_argument("--midcap-gvkeyx", default=DEFAULT_MIDCAP_GVKEYX)
    p.add_argument("--smallcap-gvkeyx", default=DEFAULT_SMALLCAP_GVKEYX)
    p.add_argument("--list", action="store_true",
                   help="Only list libraries/tables/columns + index codes, then exit.")
    args = p.parse_args(argv)
    try:
        run(args.username, args.outdir, args.min_year, args.max_year,
            args.midcap_gvkeyx, args.smallcap_gvkeyx, args.list)
    except ImportError:
        sys.exit("The 'wrds' package is required: pip install wrds pandas")


if __name__ == "__main__":
    main()
