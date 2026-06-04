"""Build the two analytical panels: executive-year and firm-year.

``executive_year_panel`` (execid x gvkey x year) is built first, in Python, so
we can attach -- for each matched executive and year -- the Revelio position
that was *active that year* (its seniority, role and modeled salary).
``firm_year_panel`` (gvkey x year) is then aggregated with SQL from the universe,
Compustat fundamentals, Execucomp NEOs and the executive-year panel.
"""

from collections import defaultdict

from . import jobcat


def _year_of(date_text):
    if not date_text:
        return None
    head = date_text.strip()[:4]
    return int(head) if head.isdigit() else None


def _positions_by_user(cur):
    by_user = defaultdict(list)
    for (user_id, rcid, role_raw, role_k150, job_category, seniority, salary,
         startdate, enddate) in cur.execute(
            "SELECT user_id, rcid, role_raw, role_k150, job_category, seniority, "
            "salary, startdate, enddate FROM revelio_positions"):
        by_user[user_id].append({
            "rcid": rcid, "role_raw": role_raw, "role_k150": role_k150,
            "job_category": job_category,
            "seniority": seniority, "salary": salary,
            "start": _year_of(startdate) if startdate else 0,
            "end": _year_of(enddate) if enddate else 9999,
        })
    return by_user


def _active_position(positions, year, focal_rcids):
    """The position active in ``year``; prefer the focal company, then seniority."""
    active = [p for p in positions if p["start"] <= year <= p["end"]]
    if not active:
        return None
    return max(active, key=lambda p: (p["rcid"] in focal_rcids, p["seniority"] or 0))


def _build_executive_year(conn):
    cur = conn.cursor()

    best = {}  # (execid, gvkey) -> (user_id, tier, score)
    for execid, gvkey, user_id, tier, score in cur.execute(
            "SELECT execid, gvkey, user_id, tier, total_score "
            "FROM exec_revelio_link WHERE is_best = 1 AND accepted = 1"):
        best[(execid, gvkey)] = (user_id, tier, score)

    gvkey_to_rcids = defaultdict(set)
    for gvkey, rcid in cur.execute("SELECT gvkey, rcid FROM company_crosswalk"):
        gvkey_to_rcids[gvkey].add(rcid)

    positions_by_user = _positions_by_user(cur)

    rows = []
    for (execid, gvkey, year, full, coname, title, ceoann, cfoann,
         salary, bonus, tdc1) in cur.execute(
            """
            SELECT a.execid, a.gvkey, a.year, a.exec_fullname, a.coname,
                   a.title, a.ceoann, a.cfoann, a.salary, a.bonus, a.tdc1
            FROM execucomp_anncomp a
            JOIN universe_firm_year u ON u.gvkey = a.gvkey AND u.year = a.year
            """):
        user_id = match_tier = match_score = None
        rev_seniority = rev_role = rev_jobcat = rev_salary = None
        match = best.get((execid, gvkey))
        if match:
            user_id, match_tier, match_score = match
            pos = _active_position(positions_by_user.get(user_id, ()),
                                   year, gvkey_to_rcids.get(gvkey, set()))
            if pos:
                rev_seniority = pos["seniority"]
                rev_role = pos["role_raw"] or pos["role_k150"]
                rev_jobcat = jobcat.normalize(pos["job_category"])
                rev_salary = pos["salary"]
        rows.append((
            execid, gvkey, year, full, coname, title,
            1 if (ceoann or "").upper() == "CEO" else 0,
            1 if (cfoann or "").upper() == "CFO" else 0,
            salary, bonus, tdc1,
            user_id, match_tier, match_score,
            rev_seniority, rev_role, rev_jobcat, rev_salary,
        ))

    cur.execute("DELETE FROM executive_year_panel;")
    cur.executemany(
        """
        INSERT OR REPLACE INTO executive_year_panel
        (execid, gvkey, year, exec_fullname, coname, title, is_ceo, is_cfo,
         salary, bonus, tdc1, user_id, match_tier, match_score,
         revelio_seniority, revelio_role, revelio_job_category, revelio_salary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


_FIRM_PANEL_SQL = """
INSERT INTO firm_year_panel
SELECT
    u.gvkey,
    (SELECT x.rcid FROM company_crosswalk x WHERE x.gvkey = u.gvkey
       ORDER BY x.match_confidence DESC LIMIT 1)              AS rcid,
    u.year,
    u.conm,
    u.sic_used,
    f.sale, f.at, f.ni, f.ceq, f.dltt, f.capx, f.xrd, f.emp,
    (SELECT COUNT(DISTINCT e.execid) FROM executive_year_panel e
       WHERE e.gvkey = u.gvkey AND e.year = u.year)           AS n_neos,
    (SELECT e.execid FROM executive_year_panel e
       WHERE e.gvkey = u.gvkey AND e.year = u.year AND e.is_ceo = 1
       LIMIT 1)                                               AS ceo_execid,
    (SELECT e.tdc1 FROM executive_year_panel e
       WHERE e.gvkey = u.gvkey AND e.year = u.year AND e.is_ceo = 1
       LIMIT 1)                                               AS ceo_tdc1,
    (SELECT SUM(e.tdc1) FROM executive_year_panel e
       WHERE e.gvkey = u.gvkey AND e.year = u.year)           AS neo_total_tdc1,
    (SELECT COUNT(DISTINCT e.execid) FROM executive_year_panel e
       WHERE e.gvkey = u.gvkey AND e.year = u.year
         AND e.user_id IS NOT NULL)                           AS n_neos_revelio_matched,
    (SELECT AVG(e.revelio_salary) FROM executive_year_panel e
       WHERE e.gvkey = u.gvkey AND e.year = u.year
         AND e.revelio_salary IS NOT NULL)                    AS avg_exec_modeled_salary
FROM universe_firm_year u
LEFT JOIN compustat_funda f ON f.gvkey = u.gvkey AND f.fyear = u.year
ORDER BY u.gvkey, u.year;
"""


def _build_firm_year(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM firm_year_panel;")
    cur.execute(_FIRM_PANEL_SQL)
    conn.commit()
    return cur.execute("SELECT COUNT(*) FROM firm_year_panel").fetchone()[0]


def build_panels(conn):
    """Build both panels; return (n_exec_year_rows, n_firm_year_rows)."""
    n_exec = _build_executive_year(conn)
    n_firm = _build_firm_year(conn)
    return n_exec, n_firm
