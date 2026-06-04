"""Tests for the combined Compustat + Revelio database build.

Run with::

    python -m unittest discover -s compustat_revelio
"""

import os
import sqlite3
import tempfile
import unittest

from compustat_revelio.build_database import (
    build_database,
    DEFAULT_COMPUSTAT,
    DEFAULT_REVELIO,
    DEFAULT_CROSSWALK,
)


class BuildDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.summary = build_database(
            DEFAULT_COMPUSTAT, DEFAULT_REVELIO, self.db_path, DEFAULT_CROSSWALK
        )
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()

    def test_sources_loaded(self):
        self.assertEqual(self.summary["compustat_rows"], 15)
        self.assertEqual(self.summary["revelio_rows"], 16)

    def test_panel_has_one_row_per_compustat_firm_year(self):
        # The panel is Compustat-driven via LEFT JOIN, so it should match the
        # Compustat firm-year count exactly.
        self.assertEqual(self.summary["panel_rows"], 15)
        count = self.conn.execute("SELECT COUNT(*) FROM firm_year_panel").fetchone()[0]
        self.assertEqual(count, 15)

    def test_ticker_match_links_apple(self):
        row = self.conn.execute(
            "SELECT rcid, match_method, headcount FROM firm_year_panel "
            "WHERE gvkey = '001690' AND year = 2021"
        ).fetchone()
        self.assertEqual(row["rcid"], "1001")
        self.assertEqual(row["match_method"], "ticker")
        self.assertEqual(row["headcount"], 149500)

    def test_manual_override_links_tesla(self):
        # Tesla has a blank ticker in Revelio, so it can only be linked via the
        # manual crosswalk.
        row = self.conn.execute(
            "SELECT rcid, match_method, match_confidence FROM firm_year_panel "
            "WHERE gvkey = '184996' AND year = 2022"
        ).fetchone()
        self.assertEqual(row["rcid"], "5005")
        self.assertEqual(row["match_method"], "manual")
        self.assertEqual(row["match_confidence"], 1.0)

    def test_derived_metrics(self):
        row = self.conn.execute(
            "SELECT sale, headcount, emp, revenue_per_employee_usd, "
            "compustat_emp_count, headcount_coverage, net_hiring "
            "FROM firm_year_panel WHERE gvkey = '001690' AND year = 2020"
        ).fetchone()
        # revenue_per_employee = sale (USD millions -> USD) / headcount
        self.assertAlmostEqual(
            row["revenue_per_employee_usd"],
            row["sale"] * 1_000_000 / row["headcount"],
            places=4,
        )
        # emp is reported in thousands; compustat_emp_count is headcount basis.
        self.assertAlmostEqual(row["compustat_emp_count"], row["emp"] * 1000)
        self.assertAlmostEqual(
            row["headcount_coverage"], row["headcount"] / (row["emp"] * 1000), places=6
        )
        self.assertEqual(row["net_hiring"], 19800 - 14100)

    def test_revelio_only_company_not_in_panel_but_unlinked(self):
        # Nvidia exists in Revelio but not Compustat; it must not appear in the
        # Compustat-driven panel and must have no crosswalk entry.
        panel = self.conn.execute(
            "SELECT COUNT(*) FROM firm_year_panel WHERE rcid = '9009'"
        ).fetchone()[0]
        self.assertEqual(panel, 0)
        link = self.conn.execute(
            "SELECT COUNT(*) FROM company_crosswalk WHERE rcid = '9009'"
        ).fetchone()[0]
        self.assertEqual(link, 0)

    def test_idempotent_rebuild(self):
        # Building again over the same path must yield identical counts.
        summary2 = build_database(
            DEFAULT_COMPUSTAT, DEFAULT_REVELIO, self.db_path, DEFAULT_CROSSWALK
        )
        self.assertEqual(self.summary["panel_rows"], summary2["panel_rows"])
        self.assertEqual(self.summary["links"], summary2["links"])


if __name__ == "__main__":
    unittest.main()
