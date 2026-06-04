"""End-to-end and unit tests for the Execucomp + Compustat + Revelio pipeline.

Runs entirely on the bundled sample data; no network or third-party deps.
"""

import os
import sqlite3
import tempfile
import unittest

from execucomp_revelio import build_database
from execucomp_revelio.build_database import DEFAULTS
from execucomp_revelio.names import canonical, name_score


def _run(min_tier="medium"):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    summary = build_database(dict(DEFAULTS), tmp.name, min_tier=min_tier)
    return tmp.name, summary


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path, cls.summary = _run()
        cls.conn = sqlite3.connect(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        os.remove(cls.db_path)

    def q(self, sql, *args):
        return self.conn.execute(sql, args).fetchall()

    # --- Universe -----------------------------------------------------------

    def test_universe_keeps_only_sp1000_in_window_ex_sic(self):
        rows = {(g, y) for g, y in
                self.q("SELECT gvkey, year FROM universe_firm_year")}
        self.assertEqual(rows, {("010001", 2014), ("010001", 2015),
                                ("010002", 2014), ("010002", 2015)})

    def test_universe_excludes_financials_and_utilities(self):
        # 010003 (bank, sich 6022) and 010004 (utility, sic 4911) are gone.
        present = {g for (g,) in self.q("SELECT DISTINCT gvkey FROM universe_firm_year")}
        self.assertNotIn("010003", present)
        self.assertNotIn("010004", present)

    def test_universe_excludes_non_index_and_expired_membership(self):
        present = {g for (g,) in self.q("SELECT DISTINCT gvkey FROM universe_firm_year")}
        self.assertNotIn("010005", present)  # never in an S&P index
        self.assertNotIn("010006", present)  # membership ended 2008

    def test_universe_excludes_out_of_window_fiscal_year(self):
        years = {y for (y,) in self.q("SELECT DISTINCT year FROM universe_firm_year")}
        self.assertNotIn(2007, years)

    # --- Company crosswalk --------------------------------------------------

    def test_crosswalk_uses_revelio_gvkey_and_ticker_fallback(self):
        methods = dict(self.q(
            "SELECT rcid, match_method FROM company_crosswalk ORDER BY rcid"))
        self.assertEqual(methods["R100"], "revelio_gvkey")
        self.assertEqual(methods["R200"], "revelio_gvkey")
        # R201 has no gvkey in the mapping; it links via the ticker fallback.
        self.assertEqual(methods["R201"], "ticker")
        self.assertEqual(
            self.q("SELECT gvkey FROM company_crosswalk WHERE rcid='R201'")[0][0],
            "010002")

    # --- Matching -----------------------------------------------------------

    def test_four_executives_matched_one_unmatched(self):
        self.assertEqual(self.summary["match"]["execs_matched"], 4)
        accepted = {e for (e,) in self.q(
            "SELECT DISTINCT execid FROM exec_revelio_link WHERE accepted=1")}
        self.assertEqual(accepted, {"E001", "E002", "E004", "E005"})
        # Michael Brown has no Revelio counterpart at the firm.
        self.assertEqual(
            self.q("SELECT COUNT(*) FROM exec_revelio_link WHERE execid='E003'")[0][0],
            0)

    def test_each_match_has_single_best(self):
        for execid in ("E001", "E002", "E004", "E005"):
            n = self.q("SELECT COUNT(*) FROM exec_revelio_link "
                       "WHERE execid=? AND is_best=1", execid)[0][0]
            self.assertEqual(n, 1, execid)

    def test_name_filter_rejects_different_surname(self):
        # Robert Smithson (U6) works at Acme but must not match Robert Smith.
        rows = self.q("SELECT user_id FROM exec_revelio_link WHERE execid='E001'")
        self.assertNotIn("U6", {r[0] for r in rows})

    # --- Work history (the primary deliverable) -----------------------------

    def test_work_history_is_complete_career_including_other_firms(self):
        rows = self.q("SELECT company, gvkey FROM exec_work_history "
                      "WHERE execid='E001' ORDER BY position_number")
        companies = [r[0] for r in rows]
        self.assertEqual(companies,
                         ["College Intern Co", "Prior Co", "Acme Midcap Corporation"])
        # Prior, non-universe employers carry a NULL gvkey; the focal firm maps.
        self.assertIsNone(rows[0][1])
        self.assertEqual(rows[-1][1], "010001")

    def test_work_history_carries_modeled_salary(self):
        salary = self.q("SELECT salary FROM exec_work_history "
                        "WHERE execid='E001' AND company='Acme Midcap Corporation'")[0][0]
        self.assertEqual(salary, 1500000.0)

    # --- Panels -------------------------------------------------------------

    def test_firm_year_panel_aggregates(self):
        row = self.q(
            "SELECT n_neos, ceo_execid, ceo_tdc1, neo_total_tdc1, "
            "n_neos_revelio_matched, avg_exec_modeled_salary "
            "FROM firm_year_panel WHERE gvkey='010001' AND year=2014")[0]
        n_neos, ceo, ceo_tdc1, neo_total, matched, avg_sal = row
        self.assertEqual(n_neos, 3)
        self.assertEqual(ceo, "E001")
        self.assertEqual(ceo_tdc1, 5200.0)
        self.assertEqual(neo_total, 9200.0)
        self.assertEqual(matched, 2)
        self.assertEqual(avg_sal, 1200000.0)  # mean(1.5M CEO, 0.9M CFO)

    def test_executive_year_panel_keeps_unmatched_rows(self):
        row = self.q("SELECT user_id, revelio_salary FROM executive_year_panel "
                     "WHERE execid='E003' AND year=2014")[0]
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])

    def test_executive_year_panel_active_position_salary(self):
        sal = self.q("SELECT revelio_salary FROM executive_year_panel "
                     "WHERE execid='E004' AND year=2015")[0][0]
        self.assertEqual(sal, 1200000.0)

    # --- Acceptance threshold knob -----------------------------------------

    def test_strict_tier_still_accepts_high_matches(self):
        path, summary = _run(min_tier="high")
        try:
            self.assertEqual(summary["match"]["execs_matched"], 4)
        finally:
            os.remove(path)

    def test_idempotent_rebuild(self):
        # Building twice into the same file yields identical row counts.
        _, s2 = _run()
        self.assertEqual(s2["firm_year_rows"], self.summary["firm_year_rows"])
        self.assertEqual(s2["work_history_rows"], self.summary["work_history_rows"])


class NameScoreTest(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(
            name_score(canonical(first="Maria", last="Garcia"),
                       canonical(full="Maria Garcia")), 1.0)

    def test_middle_initial_ignored(self):
        self.assertGreaterEqual(
            name_score(canonical(first="Robert", middle="A", last="Smith"),
                       canonical(first="Robert", last="Smith")), 0.90)

    def test_first_initial_only(self):
        s = name_score(canonical(first="Robert", last="Smith"),
                       canonical(first="Rob", last="Smith"))
        self.assertGreaterEqual(s, 0.70)
        self.assertLess(s, 0.95)

    def test_different_surname_is_weak(self):
        self.assertLess(
            name_score(canonical(first="Robert", last="Smith"),
                       canonical(first="Robert", last="Smithson")), 0.70)


if __name__ == "__main__":
    unittest.main()
