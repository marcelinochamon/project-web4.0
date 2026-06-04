"""Assemble each matched executive's complete Revelio work history.

For every accepted best match (``exec_revelio_link.is_best = 1``) we take the
Revelio ``user_id`` and pull *all* of that person's position spells -- the full
career trajectory across every company, not just the focal firm -- attaching the
Compustat ``gvkey`` of each company where Revelio's mapping provides one. This is
the primary deliverable: the executives' complete work history plus Revelio's
modeled salary for each spell.
"""

from . import jobcat


def build_work_history(conn):
    """Populate ``exec_work_history``; return (n_execs, n_position_rows)."""
    cur = conn.cursor()

    # One Revelio person per executive (best accepted match). An executive can
    # be matched at more than one firm; collapse to distinct (execid, user_id).
    pairs = cur.execute(
        "SELECT DISTINCT execid, user_id FROM exec_revelio_link "
        "WHERE is_best = 1 AND accepted = 1"
    ).fetchall()

    # rcid -> a representative gvkey (any mapped one) for labelling spells.
    rcid_to_gvkey = {}
    for rcid, gvkey in cur.execute(
            "SELECT rcid, gvkey FROM company_crosswalk"):
        rcid_to_gvkey.setdefault(rcid, gvkey)

    rows = []
    for execid, user_id in pairs:
        for (position_id, position_number, rcid, company, role_raw, role_k150,
             job_category, seniority, salary, startdate, enddate) in cur.execute(
                "SELECT position_id, position_number, rcid, company, role_raw, "
                "role_k150, job_category, seniority, salary, startdate, enddate "
                "FROM revelio_positions WHERE user_id = ? "
                "ORDER BY position_number", (user_id,)):
            rows.append((
                execid, user_id, position_id, position_number, rcid, company,
                rcid_to_gvkey.get(rcid), role_raw, role_k150,
                jobcat.normalize(job_category), seniority, salary,
                startdate, enddate,
            ))

    cur.execute("DELETE FROM exec_work_history;")
    cur.executemany(
        """
        INSERT OR IGNORE INTO exec_work_history
        (execid, user_id, position_id, position_number, rcid, company, gvkey,
         role_raw, role_k150, job_category, seniority, salary, startdate, enddate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    n_execs = len({execid for execid, _ in pairs})
    n_rows = cur.execute("SELECT COUNT(*) FROM exec_work_history").fetchone()[0]
    return n_execs, n_rows
