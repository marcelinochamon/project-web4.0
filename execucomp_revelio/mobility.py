"""Derive executive career-mobility features from the Revelio work history.

For each matched executive (one Revelio person), summarise their whole career
into a single row: how many positions/employers, how senior they got, how much
experience, and -- relative to the *focal* firm where Execucomp observed them --
whether they were promoted into the C-suite internally or hired in from outside.

Definitions (per matched (execid, user_id)):

* ``focal`` companies = the ``rcid`` set of that executive's accepted best
  matches (the firm(s) where Execucomp lists them).
* ``internal_promotion`` = the person's first spell at a focal firm was below
  executive seniority but a later focal spell reached executive level -> they
  rose through the ranks there.
* ``external_hire`` = their first focal spell was already executive level *and*
  they had prior experience at some other employer -> brought in from outside.
  (Neither flag fires for a founder whose very first job was the focal exec
  role.)

Ongoing spells (NULL end date) are closed at the latest year observed anywhere
in the positions data, so ``experience_years`` is deterministic.
"""

from collections import defaultdict

from . import config


def _max_observed_year(cur):
    years = []
    for (startdate, enddate) in cur.execute(
            "SELECT startdate, enddate FROM revelio_positions"):
        for d in (startdate, enddate):
            if d and d.strip()[:4].isdigit():
                years.append(int(d.strip()[:4]))
    return max(years) if years else config.MAX_FYEAR


def build_mobility(conn):
    """Populate ``exec_mobility``; return the number of rows written."""
    cur = conn.cursor()
    ref_year = _max_observed_year(cur)
    thresh = config.EXEC_SENIORITY_MIN

    # Focal rcids per executive (where Execucomp observed them).
    focal = defaultdict(set)
    for execid, rcid in cur.execute(
            "SELECT execid, rcid FROM exec_revelio_link "
            "WHERE is_best = 1 AND accepted = 1 AND rcid IS NOT NULL"):
        focal[execid].add(rcid)

    # All spells per matched (execid, user_id), already sorted chronologically.
    spells = defaultdict(list)
    for (execid, user_id, position_number, rcid, seniority,
         startdate, enddate) in cur.execute(
            "SELECT execid, user_id, position_number, rcid, seniority, "
            "startdate, enddate FROM exec_work_history "
            "ORDER BY execid, user_id, position_number"):
        spells[(execid, user_id)].append({
            "pos": position_number if position_number is not None else 0,
            "rcid": rcid, "seniority": seniority or 0,
            "start": _year(startdate), "end": _year(enddate),
        })

    rows = []
    for (execid, user_id), ps in spells.items():
        focal_rcids = focal.get(execid, set())
        starts = [p["start"] for p in ps if p["start"] is not None]
        ends = [(p["end"] if p["end"] is not None else ref_year) for p in ps]
        start_year = min(starts) if starts else None
        end_year = max(ends) if ends else None

        focal_spells = sorted((p for p in ps if p["rcid"] in focal_rcids),
                              key=lambda p: p["pos"])
        has_exec_focal = any(p["seniority"] >= thresh for p in focal_spells)
        internal = external = 0
        if has_exec_focal and focal_spells:
            first_focal = focal_spells[0]
            if first_focal["seniority"] < thresh:
                internal = 1
            elif any(p["pos"] < first_focal["pos"] for p in ps):
                external = 1

        # Distinct employers before the executive first joined the focal firm.
        n_prior = 0
        if focal_spells:
            first_focal_pos = focal_spells[0]["pos"]
            n_prior = len({p["rcid"] for p in ps
                           if p["pos"] < first_focal_pos and p["rcid"]})

        rows.append((
            execid, user_id,
            len(ps),
            len({p["rcid"] for p in ps if p["rcid"]}),
            max((p["seniority"] for p in ps), default=None),
            sum(1 for p in ps if p["seniority"] >= thresh),
            start_year, end_year,
            (end_year - start_year) if (start_year is not None and end_year is not None) else None,
            n_prior, internal, external,
        ))

    cur.execute("DELETE FROM exec_mobility;")
    cur.executemany(
        """
        INSERT INTO exec_mobility
        (execid, user_id, n_positions, n_employers, max_seniority,
         n_exec_positions, career_start_year, career_end_year, experience_years,
         n_prior_employers_before_focal, internal_promotion, external_hire)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def _year(date_text):
    if not date_text:
        return None
    head = date_text.strip()[:4]
    return int(head) if head.isdigit() else None
