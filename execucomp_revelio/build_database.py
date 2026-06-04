"""Build the Execucomp + Compustat + Revelio executive panel (SQLite).

Usage::

    python -m execucomp_revelio \
        --funda     path/to/compustat_funda.csv \
        --index     path/to/idxcst_his.csv \
        --execucomp path/to/execucomp_anncomp.csv \
        --individual        path/to/revelio_individual.csv \
        --positions         path/to/revelio_positions.csv \
        --company-mapping   path/to/revelio_company_mapping.csv \
        --output    execucomp_revelio.db \
        [--min-tier {high,medium,low}] [--index-gvkeyx 000400 000600]

With no source arguments the bundled sample data is used, so the pipeline runs
end-to-end out of the box::

    python -m execucomp_revelio

Pipeline stages (each idempotent; tables are dropped and rebuilt every run):

    1. load raw sources
    2. universe_firm_year   (S&P 1000, FY window, ex financials & utilities)
    3. company_crosswalk    (gvkey <-> rcid, from Revelio's gvkey)
    4. exec_revelio_link    (Execucomp exec <-> Revelio person, scored & tiered)
    5. exec_work_history    (complete Revelio career of matched executives)
    6. firm_year_panel + executive_year_panel  (the deliverables)
"""

import argparse
import logging
import os
import sqlite3

from . import config, schema, crosswalk, matching, mobility, panels, report, universe
from .export import export_tables
from .workhistory import build_work_history
from .loaders import (
    load_compustat_funda, load_index_constituents, load_execucomp,
    load_revelio_individual, load_revelio_positions, load_revelio_company_mapping,
)

LOG = logging.getLogger("execucomp_revelio")

_HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.path.join(_HERE, "sample_data")
DEFAULTS = {
    "funda": os.path.join(SAMPLE_DIR, "compustat_funda_sample.csv"),
    "index": os.path.join(SAMPLE_DIR, "compustat_idxcst_his_sample.csv"),
    "execucomp": os.path.join(SAMPLE_DIR, "execucomp_anncomp_sample.csv"),
    "individual": os.path.join(SAMPLE_DIR, "revelio_individual_sample.csv"),
    "positions": os.path.join(SAMPLE_DIR, "revelio_positions_sample.csv"),
    "company_mapping": os.path.join(SAMPLE_DIR, "revelio_company_mapping_sample.csv"),
}
DEFAULT_OUTPUT = os.path.join(_HERE, "execucomp_revelio.db")


def create_schema(conn):
    cur = conn.cursor()
    for table in schema.ALL_TABLES:
        cur.execute(f"DROP TABLE IF EXISTS {table};")
    for statement in schema.CREATE_STATEMENTS:
        cur.execute(statement)
    for index in schema.INDEXES:
        cur.execute(index)
    conn.commit()


_INSERTS = {
    "compustat_funda":
        "INSERT INTO compustat_funda (gvkey, fyear, datadate, tic, cusip, conm, "
        "sale, at, ni, ceq, dltt, capx, xrd, emp, naics, sic, sich) "
        "VALUES (" + ",".join("?" * 17) + ");",
    "compustat_index_constituents":
        "INSERT INTO compustat_index_constituents (gvkey, gvkeyx, conm, "
        "indexname, from_date, thru_date) VALUES (" + ",".join("?" * 6) + ");",
    "execucomp_anncomp":
        "INSERT INTO execucomp_anncomp (gvkey, year, execid, co_per_rol, "
        "exec_fullname, exec_fname, exec_mname, exec_lname, coname, title, "
        "ceoann, cfoann, joined_co, leftco, salary, bonus, tdc1, tdc2, age, "
        "gender) VALUES (" + ",".join("?" * 20) + ");",
    "revelio_individual":
        "INSERT INTO revelio_individual (user_id, fullname, firstname, "
        "lastname, gender, ethnicity) VALUES (" + ",".join("?" * 6) + ");",
    "revelio_positions":
        "INSERT INTO revelio_positions (position_id, user_id, rcid, company, "
        "position_number, role_raw, role_k150, role_k1500, seniority, salary, "
        "startdate, enddate, location) VALUES (" + ",".join("?" * 13) + ");",
    "revelio_company_mapping":
        "INSERT INTO revelio_company_mapping (rcid, company, ticker, cusip, "
        "isin, gvkey, lei, naics, sic) VALUES (" + ",".join("?" * 9) + ");",
}


def load_sources(conn, paths):
    cur = conn.cursor()
    loaded = {}
    for table, loader, path in [
        ("compustat_funda", load_compustat_funda, paths["funda"]),
        ("compustat_index_constituents", load_index_constituents, paths["index"]),
        ("execucomp_anncomp", load_execucomp, paths["execucomp"]),
        ("revelio_individual", load_revelio_individual, paths["individual"]),
        ("revelio_positions", load_revelio_positions, paths["positions"]),
        ("revelio_company_mapping", load_revelio_company_mapping, paths["company_mapping"]),
    ]:
        rows = loader(path)
        cur.executemany(_INSERTS[table], rows)
        loaded[table] = len(rows)
    conn.commit()
    return loaded


def build_database(paths, output_path, min_tier=config.DEFAULT_MIN_TIER,
                   index_gvkeyx=config.SP1000_INDEX_GVKEYX,
                   min_fyear=config.MIN_FYEAR, max_fyear=config.MAX_FYEAR,
                   excluded_sic_ranges=config.EXCLUDED_SIC_RANGES,
                   export_dir=None):
    """Run the full pipeline; return a summary dict of stage counts.

    If ``export_dir`` is given, the deliverable tables are also written out as
    CSV files there (in addition to the SQLite database).
    """
    if os.path.exists(output_path):
        os.remove(output_path)

    conn = sqlite3.connect(output_path)
    exported = None
    try:
        create_schema(conn)
        loaded = load_sources(conn, paths)
        LOG.info("Loaded sources: %s", loaded)

        uni = universe.build_universe(
            conn, index_gvkeyx, min_fyear, max_fyear, excluded_sic_ranges)
        LOG.info("Universe: %d firm-years (S&P 1000, FY %d-%d, ex SIC)",
                 len(uni), min_fyear, max_fyear)

        links = crosswalk.build_crosswalk(conn)
        LOG.info("Company crosswalk: %d gvkey<->rcid links", len(links))

        match_summary = matching.match_executives(conn, min_tier=min_tier)
        LOG.info("Exec matching (min_tier=%s): %d candidates, %d accepted, "
                 "%d execs matched", min_tier, match_summary["candidates"],
                 match_summary["accepted"], match_summary["execs_matched"])

        n_wh_execs, n_wh_rows = build_work_history(conn)
        LOG.info("Work history: %d positions for %d matched execs",
                 n_wh_rows, n_wh_execs)

        n_mobility = mobility.build_mobility(conn)
        LOG.info("Mobility features: %d matched executives", n_mobility)

        n_exec_year, n_firm_year = panels.build_panels(conn)
        LOG.info("Panels: %d executive-years, %d firm-years",
                 n_exec_year, n_firm_year)

        quality = report.build_report(conn)
        LOG.info("Match rate: %s (%d/%d NEOs)", quality["match_rate"],
                 quality["matched_execs"], quality["total_execs"])

        if export_dir:
            exported = export_tables(conn, export_dir)
            os.makedirs(export_dir, exist_ok=True)
            with open(os.path.join(export_dir, "match_quality_report.txt"),
                      "w", encoding="utf-8") as fh:
                fh.write(report.format_report(quality) + "\n")
            LOG.info("Exported %d CSV files + report to %s",
                     len(exported), export_dir)
    finally:
        conn.close()

    return {
        "loaded": loaded,
        "universe_rows": len(uni),
        "crosswalk_links": len(links),
        "match": match_summary,
        "work_history_execs": n_wh_execs,
        "work_history_rows": n_wh_rows,
        "mobility_rows": n_mobility,
        "executive_year_rows": n_exec_year,
        "firm_year_rows": n_firm_year,
        "report": quality,
        "output": output_path,
        "exported": exported,
    }


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Build the Execucomp + Compustat + Revelio executive panel.")
    p.add_argument("--funda", default=DEFAULTS["funda"],
                   help="Compustat funda CSV (default: bundled sample).")
    p.add_argument("--index", default=DEFAULTS["index"],
                   help="Compustat idxcst_his CSV (default: bundled sample).")
    p.add_argument("--execucomp", default=DEFAULTS["execucomp"],
                   help="Execucomp anncomp CSV (default: bundled sample).")
    p.add_argument("--individual", default=DEFAULTS["individual"],
                   help="Revelio individual CSV (default: bundled sample).")
    p.add_argument("--positions", default=DEFAULTS["positions"],
                   help="Revelio positions CSV (default: bundled sample).")
    p.add_argument("--company-mapping", default=DEFAULTS["company_mapping"],
                   dest="company_mapping",
                   help="Revelio company mapping CSV (default: bundled sample).")
    p.add_argument("--output", default=DEFAULT_OUTPUT,
                   help="Path for the output SQLite database.")
    p.add_argument("--min-tier", default=config.DEFAULT_MIN_TIER,
                   choices=config.TIER_ORDER,
                   help="Lowest match tier to accept (high=strict, "
                        "medium=balanced [default], low=lenient).")
    p.add_argument("--index-gvkeyx", nargs="+", default=list(config.SP1000_INDEX_GVKEYX),
                   help="Compustat gvkeyx codes that define the S&P 1000 "
                        "(MidCap 400 + SmallCap 600).")
    p.add_argument("--min-fyear", type=int, default=config.MIN_FYEAR)
    p.add_argument("--max-fyear", type=int, default=config.MAX_FYEAR)
    p.add_argument("--export-dir", default=None,
                   help="If set, also write the panels, work history and match "
                        "table as CSV files into this directory.")
    return p.parse_args(argv)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    paths = {
        "funda": args.funda, "index": args.index, "execucomp": args.execucomp,
        "individual": args.individual, "positions": args.positions,
        "company_mapping": args.company_mapping,
    }
    s = build_database(
        paths, args.output, min_tier=args.min_tier,
        index_gvkeyx=tuple(args.index_gvkeyx),
        min_fyear=args.min_fyear, max_fyear=args.max_fyear,
        export_dir=args.export_dir,
    )
    print(
        "Built {output}\n"
        "  Sources loaded        : {loaded}\n"
        "  Universe firm-years   : {universe_rows}\n"
        "  Company links         : {crosswalk_links}\n"
        "  Exec match candidates : {match[candidates]} "
        "({match[accepted]} accepted, {match[execs_matched]} execs)\n"
        "  Work-history rows     : {work_history_rows} "
        "for {work_history_execs} execs\n"
        "  Mobility features     : {mobility_rows} execs\n"
        "  Executive-year panel  : {executive_year_rows} rows\n"
        "  Firm-year panel       : {firm_year_rows} rows"
        .format(**s)
    )
    print()
    print(report.format_report(s["report"]))
    if s["exported"]:
        print("  CSV exports:")
        for table, (path, count) in s["exported"].items():
            print(f"    {path} ({count} rows)")


if __name__ == "__main__":
    main()
