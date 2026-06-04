"""Extract the six pipeline inputs directly from WRDS.

Runs on **your** WRDS access (it needs your credentials + network, neither of
which exist in a sandbox). Uses the official ``wrds`` package and writes CSVs
whose headers match exactly what ``execucomp_revelio`` expects::

    pip install wrds pandas
    python -m execucomp_revelio.wrds_extract --username YOUR_WRDS_ID --outdir ./wrds_csv
    python -m execucomp_revelio \
        --funda ./wrds_csv/compustat_funda.csv --index ./wrds_csv/compustat_idxcst_his.csv \
        --execucomp ./wrds_csv/execucomp_anncomp.csv \
        --individual ./wrds_csv/revelio_individual.csv \
        --positions ./wrds_csv/revelio_positions.csv \
        --company-mapping ./wrds_csv/revelio_company_mapping.csv \
        --export-dir ./out

Table/column names below are pinned to the WRDS schema confirmed via ``--list``
(comp / comp_execucomp / revelio). The Revelio individual data only carries
``fullname`` (first/last are derived) and gender/ethnicity as predicted
columns; positions carry a role *taxonomy* (``role_k1500_v2``) rather than free
text. Because we only need the executives, the Revelio pull is restricted to
senior positions at the focal firms, then those people's *entire* histories.

Run ``--list`` first if you want to re-confirm names; all queries are plain
``db.raw_sql`` (avoiding literal ``%``, which psycopg2 misreads as a bind
parameter under SQLAlchemy 2).
"""

import argparse
import os
import sys

TABLES = {
    "funda": "comp.funda",
    "company": "comp.company",
    "idxcst_his": "comp.idxcst_his",
    "idx_index": "comp.idx_index",
    "anncomp": "comp_execucomp.anncomp",
    "rev_individual": "revelio.individual_user",
    "rev_positions": "revelio.individual_positions",
    "rev_company": "revelio.company_mapping",
    "rev_role_lookup": "revelio.individual_role_lookup_v2",
}

# Confirmed gvkeyx codes (comp.idx_index): S&P MidCap 400 / SmallCap 600.
DEFAULT_MIDCAP_GVKEYX = "024248"
DEFAULT_SMALLCAP_GVKEYX = "030824"

# Output column order per file (must match execucomp_revelio.loaders).
COLS = {
    "funda": ["gvkey", "fyear", "datadate", "tic", "cusip", "cik", "conm",
              "sale", "at", "ni", "ceq", "dltt", "capx", "xrd", "emp",
              "naics", "sic", "sich"],
    "idx": ["gvkey", "gvkeyx", "conm", "indexname", "from_date", "thru_date"],
    "anncomp": ["gvkey", "year", "execid", "co_per_rol", "exec_fullname",
                "exec_fname", "exec_mname", "exec_lname", "coname", "title",
                "ceoann", "cfoann", "joined_co", "leftco", "salary", "bonus",
                "tdc1", "tdc2", "age", "gender"],
    "individual": ["user_id", "fullname", "firstname", "lastname", "gender",
                   "ethnicity"],
    "positions": ["position_id", "user_id", "rcid", "company", "position_number",
                  "role_raw", "role_k150", "role_k1500", "job_category",
                  "seniority", "salary", "startdate", "enddate", "location"],
    "mapping": ["rcid", "company", "ticker", "cusip", "isin", "gvkey", "lei",
                "naics", "sic"],
}


def _chunks(seq, n=900):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _in_list(values):
    return ",".join("'" + str(v).replace("'", "''") + "'" for v in values)


def _norm_gvkey(series):
    """Compustat-style 6-char zero-padded gvkey (so Revelio joins line up)."""
    s = series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    return s.where(s.isin(["", "nan", "None"]), s.str.zfill(6))


def _id_col(series):
    """Integer-like id column as plain strings (NaN -> <NA>)."""
    import pandas as pd
    return pd.to_numeric(series, errors="coerce").astype("Int64").astype(str)


def _clean_ids(series):
    """Clean integer-like ids (rcid/user_id) to plain string form, NaN dropped."""
    import pandas as pd
    return (pd.to_numeric(series, errors="coerce").dropna()
            .astype("int64").astype(str))


def _concat(frames):
    import pandas as pd
    frames = [f for f in frames if f is not None and len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _write(df, key, outdir, name):
    import pandas as pd
    cols = COLS[key]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    path = os.path.join(outdir, name)
    df[cols].to_csv(path, index=False)
    return path, len(df)


# --- Discovery -------------------------------------------------------------

def list_schema(db):
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
    try:
        allidx = db.raw_sql(f"SELECT gvkeyx, conm FROM {TABLES['idx_index']}")
        mask = allidx["conm"].str.contains(
            "midcap 400|smallcap 600|s&p 1000", case=False, na=False)
        print("\nIndex gvkeyx candidates:\n", allidx[mask].to_string(index=False))
    except Exception as exc:                           # noqa: BLE001
        print("idx_index lookup failed:", exc)
    # Role lookup (role_k1500 -> job_category / role_k7) columns + sample.
    try:
        rl = db.raw_sql(f"SELECT * FROM {TABLES['rev_role_lookup']} LIMIT 5")
        print(f"\n{TABLES['rev_role_lookup']} columns:\n", rl.columns.tolist())
        print(rl.to_string(index=False))
    except Exception as exc:                           # noqa: BLE001
        print(f"{TABLES['rev_role_lookup']} sample failed:", exc)


# --- Extraction steps ------------------------------------------------------

def universe(db, midcap, smallcap, min_year, max_year):
    sql = f"""
        SELECT gvkey, gvkeyx, "from" AS from_date, thru AS thru_date
        FROM {TABLES['idxcst_his']}
        WHERE gvkeyx IN ('{midcap}','{smallcap}')
          AND ("from" IS NULL OR EXTRACT(YEAR FROM "from") <= {max_year})
          AND (thru   IS NULL OR EXTRACT(YEAR FROM thru)   >= {min_year})
    """
    df = db.raw_sql(sql)
    df["gvkey"] = _norm_gvkey(df["gvkey"])
    df["indexname"] = df["gvkeyx"].map(
        {midcap: "S&P MidCap 400", smallcap: "S&P SmallCap 600"})
    df["conm"] = None
    return df, sorted(df["gvkey"].unique())


def extract_funda(db, gvkeys, min_year, max_year):
    frames = []
    for chunk in _chunks(gvkeys):
        frames.append(db.raw_sql(f"""
            SELECT f.gvkey, f.fyear, f.datadate, f.tic, f.cusip, c.cik, f.conm,
                   f.sale, f.at, f.ni, f.ceq, f.dltt, f.capx, f.xrd, f.emp,
                   c.naics, c.sic, f.sich
            FROM {TABLES['funda']} f
            LEFT JOIN {TABLES['company']} c ON c.gvkey = f.gvkey
            WHERE f.indfmt='INDL' AND f.datafmt='STD' AND f.popsrc='D'
              AND f.consol='C' AND f.fyear BETWEEN {min_year} AND {max_year}
              AND f.gvkey IN ({_in_list(chunk)})
        """))
    df = _concat(frames)
    if len(df):
        df["gvkey"] = _norm_gvkey(df["gvkey"])
    return df


def extract_anncomp(db, gvkeys, min_year, max_year):
    frames = []
    for chunk in _chunks(gvkeys):
        frames.append(db.raw_sql(f"""
            SELECT gvkey, year, execid, co_per_rol, exec_fullname,
                   exec_fname, exec_mname, exec_lname, coname, title,
                   ceoann, cfoann, joined_co, leftofc AS leftco,
                   salary, bonus, tdc1, tdc2, age, gender
            FROM {TABLES['anncomp']}
            WHERE year BETWEEN {min_year} AND {max_year}
              AND gvkey IN ({_in_list(chunk)})
        """))
    df = _concat(frames)
    if len(df):
        df["gvkey"] = _norm_gvkey(df["gvkey"])
    return df


def extract_mapping(db, gvkey_set):
    """All company_mapping rows with a gvkey, normalised and filtered to universe."""
    df = db.raw_sql(f"""
        SELECT rcid, company, ticker, cusip, isin, gvkey, lei,
               naics_code AS naics, NULL AS sic
        FROM {TABLES['rev_company']} WHERE gvkey IS NOT NULL
    """)
    if len(df):
        df["gvkey"] = _norm_gvkey(df["gvkey"])
        df["rcid"] = _id_col(df["rcid"])
        df = df[df["gvkey"].isin(gvkey_set)]
    return df


def _exec_name_keys(anncomp):
    """'lastname|firstinitial' keys for every Execucomp executive."""
    ln = anncomp["exec_lname"].astype(str).str.strip().str.lower()
    fi = anncomp["exec_fname"].astype(str).str.strip().str.lower().str[:1]
    keys = (ln + "|" + fi)[ln.ne("") & ~ln.isin(["nan", "none"])]
    return sorted(set(keys))


# SQL fragment that builds the same 'lastname|firstinitial' key from a Revelio
# fullname, so it can be matched against the Execucomp keys.
_REV_NAMEKEY = (
    "lower(reverse(split_part(reverse(trim(u.fullname)), ' ', 1))) || '|' || "
    "lower(left(split_part(trim(u.fullname), ' ', 1), 1))")


def _seed_users(db, focal_rcids, seed, seniority_min, exec_keys):
    """Stage 1: pick the candidate-executive user_ids at the focal firms.

    seed='name' (default): Revelio people at a focal firm whose lastname+first
    initial matches an Execucomp NEO -- ANY seniority, so no executive is lost
    to a seniority mislabel. Falls back to 'seniority' if the temp-table join
    isn't permitted. seed='seniority': senior positions only. seed='all': every
    employee at the focal firms (complete but very large).
    """
    import pandas as pd
    if seed == "name":
        try:
            pd.DataFrame({"rcid": [int(r) for r in focal_rcids]}).to_sql(
                "tmp_er_rcid", db.engine, if_exists="replace", index=False)
            pd.DataFrame({"namekey": exec_keys}).to_sql(
                "tmp_er_key", db.engine, if_exists="replace", index=False)
            try:
                u = db.raw_sql(f"""
                    SELECT DISTINCT p.user_id
                    FROM {TABLES['rev_positions']} p
                    JOIN tmp_er_rcid r ON r.rcid = p.rcid
                    JOIN {TABLES['rev_individual']} u ON u.user_id = p.user_id
                    JOIN tmp_er_key k ON k.namekey = {_REV_NAMEKEY}
                """)
            finally:
                for t in ("tmp_er_rcid", "tmp_er_key"):
                    db.connection.exec_driver_sql(f"DROP TABLE IF EXISTS {t}")
            return sorted(_clean_ids(u["user_id"]))
        except Exception as exc:                       # noqa: BLE001
            print(f"  name-seed temp-table join failed ({exc}); "
                  f"falling back to seniority>={seniority_min}")
            seed = "seniority"

    users = set()
    for chunk in _chunks(focal_rcids):
        cond = f"AND seniority >= {seniority_min}" if seed == "seniority" else ""
        u = db.raw_sql(f"SELECT DISTINCT user_id FROM {TABLES['rev_positions']} "
                       f"WHERE rcid IN ({_in_list(chunk)}) {cond}")
        users.update(_clean_ids(u["user_id"]))
    return sorted(users)


def extract_revelio(db, focal_rcids, seed, seniority_min, exec_keys):
    """Seed candidate executives, then pull their ENTIRE position history.

    Stage 2 applies NO seniority filter, so each executive's junior/early-career
    positions (seniority < 5) are included -- the full work history.
    """
    users = _seed_users(db, focal_rcids, seed, seniority_min, exec_keys)

    pos_frames, ind_frames = [], []
    for chunk in _chunks(users):
        pos_frames.append(db.raw_sql(f"""
            SELECT position_id, user_id, rcid, position_number,
                   role_k1500_v2 AS role_k1500, seniority, salary,
                   startdate, enddate,
                   concat_ws(', ', city, state, country) AS location
            FROM {TABLES['rev_positions']} WHERE user_id IN ({_in_list(chunk)})
        """))
        ind_frames.append(db.raw_sql(f"""
            SELECT user_id, fullname,
                   split_part(trim(fullname), ' ', 1) AS firstname,
                   reverse(split_part(reverse(trim(fullname)), ' ', 1)) AS lastname,
                   sex_predicted AS gender, ethnicity_predicted AS ethnicity
            FROM {TABLES['rev_individual']} WHERE user_id IN ({_in_list(chunk)})
        """))
    positions, individuals = _concat(pos_frames), _concat(ind_frames)
    for df in (positions, individuals):
        if "user_id" in df.columns and len(df):
            df["user_id"] = _id_col(df["user_id"])
    if len(positions):
        positions["rcid"] = _id_col(positions["rcid"])
    return positions, individuals, len(users)


def attach_job_category(db, positions):
    """Map each position's role_k1500 code to the 7-value job family (role_k7).

    Auto-detects the key (``*k1500*``) and category (``*k7*`` label) columns in
    the role-lookup table; leaves ``job_category`` null with a note if they
    can't be found (run ``--list`` to see the lookup's actual columns).
    """
    if not len(positions):
        positions["job_category"] = None
        return positions
    try:
        cols = db.raw_sql(
            f"SELECT * FROM {TABLES['rev_role_lookup']} LIMIT 0").columns.tolist()
    except Exception as exc:                           # noqa: BLE001
        print(f"  role lookup unavailable ({exc}); job_category left null")
        positions["job_category"] = None
        return positions
    # Confirmed schema: key=role_k1500_v2, category=job_category_v2. Fall back to
    # fuzzy detection for other vintages.
    key_col = ("role_k1500_v2" if "role_k1500_v2" in cols
               else next((c for c in cols if "k1500" in c), None))
    cat_col = ("job_category_v2" if "job_category_v2" in cols
               else "job_category" if "job_category" in cols
               else next((c for c in cols if "k7" in c and ("label" in c or "name" in c)), None)
               or next((c for c in cols if "k7" in c), None)
               or next((c for c in cols if "category" in c.lower()), None))
    if not key_col or not cat_col:
        print(f"  couldn't find k1500/k7 columns in {TABLES['rev_role_lookup']} "
              f"({cols}); job_category left null -- run --list and tell me the names")
        positions["job_category"] = None
        return positions
    lk = db.raw_sql(f"SELECT DISTINCT {key_col}, {cat_col} "
                    f"FROM {TABLES['rev_role_lookup']}")
    lookup = dict(zip(lk[key_col].astype(str), lk[cat_col]))
    positions["job_category"] = positions["role_k1500"].astype(str).map(lookup)
    print(f"  job_category mapped via {key_col} -> {cat_col}")
    return positions


def attach_company_names(db, positions):
    """Fill positions.company by mapping every rcid (incl. prior employers)."""
    if not len(positions):
        positions["company"] = None
        return positions
    rcids = sorted(positions["rcid"].dropna().unique())
    frames = []
    for chunk in _chunks(rcids):
        frames.append(db.raw_sql(
            f"SELECT rcid, company FROM {TABLES['rev_company']} "
            f"WHERE rcid IN ({_in_list(chunk)})"))
    names = _concat(frames)
    if len(names):
        names["rcid"] = _id_col(names["rcid"])
        lookup = dict(zip(names["rcid"], names["company"]))
        positions["company"] = positions["rcid"].map(lookup)
    else:
        positions["company"] = None
    return positions


# --- Orchestration ---------------------------------------------------------

def run(username, outdir, min_year, max_year, midcap, smallcap,
        seed, focal_seniority_min, do_list):
    import wrds
    os.makedirs(outdir, exist_ok=True)
    db = wrds.Connection(wrds_username=username)
    try:
        if do_list:
            list_schema(db)
            return

        idx, gvkeys = universe(db, midcap, smallcap, min_year, max_year)
        gvkey_set = set(gvkeys)
        print(f"S&P 1000 universe: {len(gvkeys)} gvkeys")
        print("  ", _write(idx, "idx", outdir, "compustat_idxcst_his.csv"))

        print("  ", _write(extract_funda(db, gvkeys, min_year, max_year),
                           "funda", outdir, "compustat_funda.csv"))
        anncomp = extract_anncomp(db, gvkeys, min_year, max_year)
        print("  ", _write(anncomp, "anncomp", outdir, "execucomp_anncomp.csv"))
        exec_keys = _exec_name_keys(anncomp)
        print(f"  executive name keys: {len(exec_keys)}")

        mapping = extract_mapping(db, gvkey_set)
        print("  ", _write(mapping, "mapping", outdir, "revelio_company_mapping.csv"))
        focal_rcids = sorted(set(_clean_ids(mapping["rcid"])))
        print(f"  focal rcids: {len(focal_rcids)}")

        positions, individuals, n_users = extract_revelio(
            db, focal_rcids, seed, focal_seniority_min, exec_keys)
        positions = attach_company_names(db, positions)
        positions = attach_job_category(db, positions)
        print(f"  candidate-executive users ({seed}-seeded): {n_users}")
        print("  ", _write(positions, "positions", outdir, "revelio_positions.csv"))
        print("  ", _write(individuals, "individual", outdir, "revelio_individual.csv"))
        print(f"\nDone -> {outdir}/  (now run `python -m execucomp_revelio ...`)")
    finally:
        db.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--username", required=True)
    p.add_argument("--outdir", default="./wrds_csv")
    p.add_argument("--min-year", type=int, default=2009)
    p.add_argument("--max-year", type=int, default=2019)
    p.add_argument("--midcap-gvkeyx", default=DEFAULT_MIDCAP_GVKEYX)
    p.add_argument("--smallcap-gvkeyx", default=DEFAULT_SMALLCAP_GVKEYX)
    p.add_argument("--seed", choices=["name", "seniority", "all"], default="name",
                   help="How to pick candidate executives at the focal firms: "
                        "'name' (default) = Execucomp name-match at ANY seniority "
                        "(won't miss execs mislabeled below a seniority cutoff); "
                        "'seniority' = senior positions only; 'all' = every "
                        "employee (complete but very large). Stage 2 always "
                        "pulls each selected person's FULL history.")
    p.add_argument("--focal-seniority-min", type=int, default=5,
                   help="Min Revelio seniority for --seed seniority (default 5).")
    p.add_argument("--list", action="store_true",
                   help="List libraries/tables/columns + index codes, then exit.")
    args = p.parse_args(argv)
    try:
        run(args.username, args.outdir, args.min_year, args.max_year,
            args.midcap_gvkeyx, args.smallcap_gvkeyx, args.seed,
            args.focal_seniority_min, args.list)
    except ImportError:
        sys.exit("The 'wrds' package is required: pip install wrds pandas")


if __name__ == "__main__":
    main()
