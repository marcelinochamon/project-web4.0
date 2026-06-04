"""Match Execucomp executives to Revelio individuals (scored & tiered).

The match is *scoped by company*: for each Execucomp executive at a ``gvkey`` we
only consider Revelio people who held a position at one of that company's
``rcid`` entities (from ``company_crosswalk``). Within that scope we score the
name and corroborate with executive seniority/role and tenure-date overlap:

    total_score = name*W_NAME + seniority_ok*W_SENIORITY + date_overlap*W_DATE

and assign a tier (high / medium / low). Acceptance is governed by a single
threshold (``min_tier``) so the user can slide from strict -> balanced ->
lenient *after seeing results* -- the full scored candidate table is always
written, accepted or not, with ``accepted`` and ``is_best`` flags.

Salary is deliberately a reported sanity-check ratio, never a gating signal,
because Revelio's *modeled* salary is not comparable to Execucomp's reported
cash salary.
"""

from collections import defaultdict

from . import config
from .names import canonical, name_score


def _year_of(date_text):
    if not date_text:
        return None
    head = date_text.strip()[:4]
    return int(head) if head.isdigit() else None


def _overlaps(win_a, win_b):
    """True if two (lo, hi) inclusive year windows overlap."""
    (a0, a1), (b0, b1) = win_a, win_b
    return a0 <= b1 and b0 <= a1


def _exec_records(cur):
    """Aggregate Execucomp to one record per (execid, gvkey) within the universe.

    Returns ``{(execid, gvkey): info}`` where info carries the canonical name,
    the service-year window, and a representative base salary (USD).
    """
    rows = cur.execute(
        """
        SELECT a.execid, a.gvkey, a.year, a.exec_fname, a.exec_mname,
               a.exec_lname, a.exec_fullname, a.joined_co, a.leftco, a.salary
        FROM execucomp_anncomp a
        JOIN universe_firm_year u ON u.gvkey = a.gvkey AND u.year = a.year
        """
    ).fetchall()

    acc = {}
    for (execid, gvkey, year, fn, mn, ln, full, joined, left, salary) in rows:
        key = (execid, gvkey)
        info = acc.get(key)
        if info is None:
            info = acc[key] = {
                "name": canonical(first=fn, middle=mn, last=ln, full=full),
                "exec_name": full or " ".join(p for p in (fn, ln) if p),
                "years": set(), "joined": None, "left": None, "salaries": [],
            }
        if year is not None:
            info["years"].add(year)
        jy = _year_of(joined)
        if jy is not None:
            info["joined"] = jy if info["joined"] is None else min(info["joined"], jy)
        ly = _year_of(left)
        if ly is not None:
            info["left"] = ly if info["left"] is None else max(info["left"], ly)
        if salary is not None:
            info["salaries"].append(salary)

    for info in acc.values():
        years = info["years"] or {None}
        ys = {y for y in years if y is not None}
        lo = info["joined"] if info["joined"] is not None else (min(ys) if ys else 0)
        hi = info["left"] if info["left"] is not None else (max(ys) if ys else 9999)
        info["window"] = (min(lo, hi), max(lo, hi))
        # Representative base salary in USD (Execucomp salary is in $ thousands).
        info["salary_usd"] = (
            sum(info["salaries"]) / len(info["salaries"]) * 1000.0
            if info["salaries"] else None
        )
    return acc


def _positions_by_rcid(cur):
    """Return ``{rcid: [position dict, ...]}`` for all Revelio positions."""
    by_rcid = defaultdict(list)
    for (position_id, user_id, rcid, role_raw, seniority, salary,
         startdate, enddate) in cur.execute(
            "SELECT position_id, user_id, rcid, role_raw, seniority, salary, "
            "startdate, enddate FROM revelio_positions"):
        if not rcid:
            continue
        s = _year_of(startdate)
        e = _year_of(enddate)
        by_rcid[rcid].append({
            "position_id": position_id, "user_id": user_id, "rcid": rcid,
            "role_raw": role_raw, "seniority": seniority, "salary": salary,
            "win": (s if s is not None else 0, e if e is not None else 9999),
            "has_dates": s is not None or e is not None,
        })
    return by_rcid


def _role_is_exec(role_raw):
    if not role_raw:
        return False
    low = role_raw.lower()
    return any(kw in low for kw in config.EXEC_ROLE_KEYWORDS)


def _tier(name, seniority_ok, date_overlap):
    corroborated = seniority_ok or date_overlap
    if name >= config.NAME_STRONG and corroborated:
        return "high"
    if name >= config.NAME_STRONG or (name >= config.NAME_WEAK and corroborated):
        return "medium"
    if name >= config.NAME_WEAK:
        return "low"
    return None


def match_executives(conn, min_tier=config.DEFAULT_MIN_TIER):
    """Score Execucomp<->Revelio candidates and load ``exec_revelio_link``.

    Returns a summary dict (candidate count, accepted count, distinct execs
    matched). Every candidate scoring at least a weak name match is recorded;
    ``accepted`` reflects ``min_tier`` and ``is_best`` flags the top accepted
    Revelio person per (execid, gvkey).
    """
    cur = conn.cursor()
    min_rank = config.TIER_ORDER.index(min_tier)

    execs = _exec_records(cur)
    positions_by_rcid = _positions_by_rcid(cur)
    individuals = {
        uid: canonical(first=fn, last=ln, full=full)
        for uid, fn, ln, full in cur.execute(
            "SELECT user_id, firstname, lastname, fullname FROM revelio_individual")
    }

    gvkey_to_rcids = defaultdict(set)
    for gvkey, rcid in cur.execute("SELECT gvkey, rcid FROM company_crosswalk"):
        gvkey_to_rcids[gvkey].add(rcid)

    link_rows = []
    accepted_execs = set()

    for (execid, gvkey), info in execs.items():
        rcids = gvkey_to_rcids.get(gvkey)
        if not rcids:
            continue

        # Gather candidate positions at the company, grouped by Revelio person.
        per_user = defaultdict(list)
        for rcid in rcids:
            for pos in positions_by_rcid.get(rcid, ()):
                per_user[pos["user_id"]].append(pos)

        best_for_pair = None
        for user_id, positions in per_user.items():
            rev_name = individuals.get(user_id) or canonical()
            nscore = name_score(info["name"], rev_name)
            if nscore < config.NAME_WEAK:
                continue

            seniority_ok = any((p["seniority"] or 0) >= config.EXEC_SENIORITY_MIN
                               for p in positions)
            role_ok = any(_role_is_exec(p["role_raw"]) for p in positions)
            date_overlap = any(p["has_dates"] and _overlaps(p["win"], info["window"])
                               for p in positions)

            tier = _tier(nscore, seniority_ok or role_ok, date_overlap)
            if tier is None:
                continue

            # Pick the most informative corroborating position to record.
            corrob = _pick_position(positions, info["window"])
            sal_ratio = None
            if corrob["salary"] and info["salary_usd"]:
                sal_ratio = round(corrob["salary"] / info["salary_usd"], 3)

            total = round(
                nscore * config.W_NAME
                + (1.0 if (seniority_ok or role_ok) else 0.0) * config.W_SENIORITY
                + (1.0 if date_overlap else 0.0) * config.W_DATE,
                4,
            )
            accepted = config.TIER_ORDER.index(tier) >= min_rank

            row = {
                "execid": execid, "gvkey": gvkey, "user_id": user_id,
                "position_id": corrob["position_id"], "rcid": corrob["rcid"],
                "exec_name": info["exec_name"],
                "revelio_name": _display_name(rev_name),
                "name_score": round(nscore, 4),
                "seniority_ok": int(seniority_ok or role_ok),
                "role_ok": int(role_ok), "date_overlap": int(date_overlap),
                "salary_ratio": sal_ratio, "total_score": total,
                "tier": tier, "accepted": int(accepted), "is_best": 0,
            }
            link_rows.append(row)
            if accepted:
                accepted_execs.add((execid, gvkey))
                key = (total, nscore, row["seniority_ok"])
                if best_for_pair is None or key > best_for_pair[0]:
                    best_for_pair = (key, row)

        if best_for_pair is not None:
            best_for_pair[1]["is_best"] = 1

    cur.execute("DELETE FROM exec_revelio_link;")
    cur.executemany(
        """
        INSERT INTO exec_revelio_link
        (execid, gvkey, user_id, position_id, rcid, exec_name, revelio_name,
         name_score, seniority_ok, role_ok, date_overlap, salary_ratio,
         total_score, tier, accepted, is_best)
        VALUES (:execid, :gvkey, :user_id, :position_id, :rcid, :exec_name,
                :revelio_name, :name_score, :seniority_ok, :role_ok,
                :date_overlap, :salary_ratio, :total_score, :tier, :accepted,
                :is_best)
        """,
        link_rows,
    )
    conn.commit()
    return {
        "candidates": len(link_rows),
        "accepted": sum(r["accepted"] for r in link_rows),
        "execs_matched": len(accepted_execs),
    }


def _pick_position(positions, exec_window):
    """Choose the most informative position to attach to a link row.

    Preference: executive-level AND date-overlapping > date-overlapping >
    executive-level > highest seniority.
    """
    def rank(p):
        exec_lvl = (p["seniority"] or 0) >= config.EXEC_SENIORITY_MIN or _role_is_exec(p["role_raw"])
        overlap = p["has_dates"] and _overlaps(p["win"], exec_window)
        return (exec_lvl and overlap, overlap, exec_lvl, p["seniority"] or 0)

    return max(positions, key=rank)


def _display_name(name):
    parts = [p for p in (name.get("first"), name.get("last")) if p]
    return " ".join(parts).title() if parts else None
