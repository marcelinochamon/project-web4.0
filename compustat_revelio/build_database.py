"""Build a combined Compustat + Revelio SQLite database.

Usage::

    python -m compustat_revelio.build_database \
        --compustat path/to/compustat.csv \
        --revelio   path/to/revelio.csv \
        --output    compustat_revelio.db \
        [--crosswalk path/to/manual_links.csv]

With no ``--compustat``/``--revelio`` arguments the bundled sample data is
used, so the pipeline runs end-to-end out of the box::

    python -m compustat_revelio.build_database

The build is idempotent: existing tables are dropped and rebuilt on each run.
"""

import argparse
import logging
import os
import sqlite3

from . import schema
from . import linking
from .loaders import load_compustat, load_revelio

LOG = logging.getLogger("compustat_revelio")

_HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.path.join(_HERE, "sample_data")
DEFAULT_COMPUSTAT = os.path.join(SAMPLE_DIR, "compustat_sample.csv")
DEFAULT_REVELIO = os.path.join(SAMPLE_DIR, "revelio_sample.csv")
DEFAULT_CROSSWALK = os.path.join(SAMPLE_DIR, "manual_crosswalk.csv")
DEFAULT_OUTPUT = os.path.join(_HERE, "compustat_revelio.db")

# SQL that materialises the merged firm-year panel from the raw tables and the
# crosswalk. A LEFT JOIN keeps every Compustat firm-year, even where no Revelio
# match exists, so coverage gaps are explicit rather than silently dropped.
_BUILD_PANEL_SQL = """
INSERT INTO firm_year_panel
SELECT
    c.gvkey,
    x.rcid,
    c.fyear AS year,
    c.conm,
    r.company,
    c.tic,
    c.cusip,
    c.naics,
    c.sic,
    c.sale,
    c.at,
    c.ni,
    c.emp,
    r.headcount,
    r.hires,
    r.departures,
    r.attrition_rate,
    r.avg_tenure,
    r.avg_salary,
    CASE WHEN r.headcount > 0 AND c.sale IS NOT NULL
         THEN c.sale * 1000000.0 / r.headcount END        AS revenue_per_employee_usd,
    CASE WHEN c.emp > 0 THEN c.emp * 1000.0 END            AS compustat_emp_count,
    CASE WHEN c.emp > 0 AND r.headcount IS NOT NULL
         THEN r.headcount / (c.emp * 1000.0) END           AS headcount_coverage,
    CASE WHEN r.hires IS NOT NULL AND r.departures IS NOT NULL
         THEN r.hires - r.departures END                   AS net_hiring,
    x.match_method,
    x.match_confidence
FROM compustat_fundamentals c
LEFT JOIN company_crosswalk x ON x.gvkey = c.gvkey
LEFT JOIN revelio_workforce r ON r.rcid = x.rcid AND r.year = c.fyear
ORDER BY c.gvkey, c.fyear;
"""


def create_schema(conn):
    """Drop any existing tables and recreate the full schema."""
    cur = conn.cursor()
    for table in schema.ALL_TABLES:
        cur.execute(f"DROP TABLE IF EXISTS {table};")
    for statement in schema.CREATE_STATEMENTS:
        cur.execute(statement)
    for index in schema.INDEXES:
        cur.execute(index)
    conn.commit()


def load_sources(conn, compustat_path, revelio_path):
    """Load raw Compustat and Revelio CSVs into their tables."""
    cur = conn.cursor()

    compustat_rows = load_compustat(compustat_path)
    cur.executemany(
        "INSERT INTO compustat_fundamentals "
        "(gvkey, fyear, datadate, tic, cusip, conm, sale, at, ni, emp, naics, sic) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
        compustat_rows,
    )

    revelio_rows = load_revelio(revelio_path)
    cur.executemany(
        "INSERT INTO revelio_workforce "
        "(rcid, company, year, headcount, hires, departures, attrition_rate, "
        "avg_tenure, avg_salary, ticker) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
        revelio_rows,
    )
    conn.commit()
    return len(compustat_rows), len(revelio_rows)


def build_panel(conn):
    """Populate the merged firm-year panel from the raw tables + crosswalk."""
    cur = conn.cursor()
    cur.execute("DELETE FROM firm_year_panel;")
    cur.execute(_BUILD_PANEL_SQL)
    conn.commit()
    return cur.execute("SELECT COUNT(*) FROM firm_year_panel;").fetchone()[0]


def build_database(compustat_path, revelio_path, output_path, crosswalk_path=None):
    """Run the full pipeline and return summary counts.

    Returns a dict with row counts for each stage so callers (CLI, tests) can
    report or assert on the result.
    """
    # Start each build from a clean file so stale tables never linger.
    if os.path.exists(output_path):
        os.remove(output_path)

    conn = sqlite3.connect(output_path)
    try:
        create_schema(conn)
        n_compustat, n_revelio = load_sources(conn, compustat_path, revelio_path)
        LOG.info("Loaded %d Compustat firm-years and %d Revelio firm-years",
                 n_compustat, n_revelio)

        manual = crosswalk_path if crosswalk_path and os.path.exists(crosswalk_path) else None
        links = linking.build_crosswalk(conn, manual_path=manual)
        LOG.info("Built %d company links (gvkey <-> rcid)", len(links))

        n_panel = build_panel(conn)
        n_matched = conn.execute(
            "SELECT COUNT(*) FROM firm_year_panel WHERE rcid IS NOT NULL;"
        ).fetchone()[0]
        LOG.info("Merged panel: %d firm-years (%d with Revelio workforce data)",
                 n_panel, n_matched)
    finally:
        conn.close()

    return {
        "compustat_rows": n_compustat,
        "revelio_rows": n_revelio,
        "links": len(links),
        "panel_rows": n_panel,
        "panel_matched": n_matched,
        "output": output_path,
    }


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Build a combined Compustat + Revelio SQLite database.")
    parser.add_argument("--compustat", default=DEFAULT_COMPUSTAT,
                        help="Path to Compustat fundamentals CSV "
                             "(default: bundled sample data).")
    parser.add_argument("--revelio", default=DEFAULT_REVELIO,
                        help="Path to Revelio workforce CSV "
                             "(default: bundled sample data).")
    parser.add_argument("--crosswalk", default=DEFAULT_CROSSWALK,
                        help="Optional manual gvkey/rcid override CSV "
                             "(default: bundled sample overrides if present).")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help="Path for the output SQLite database.")
    return parser.parse_args(argv)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    summary = build_database(args.compustat, args.revelio, args.output, args.crosswalk)
    print(
        "Built {output}\n"
        "  Compustat firm-years : {compustat_rows}\n"
        "  Revelio firm-years   : {revelio_rows}\n"
        "  Company links        : {links}\n"
        "  Merged panel rows    : {panel_rows} ({panel_matched} with workforce data)"
        .format(**summary)
    )


if __name__ == "__main__":
    main()
