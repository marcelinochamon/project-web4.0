"""Match-quality report: how well did Execucomp executives link to Revelio?

Produces the numbers you need to decide whether the current acceptance
threshold (``--min-tier``) is too strict or too lenient, and to spot likely bad
matches before using the panel:

* overall NEO match rate, and the count of accepted matches by tier;
* how many accepted (execid, gvkey) pairs are *ambiguous* (more than one
  Revelio person accepted), which warrants manual review;
* the Revelio/Execucomp salary-ratio distribution and a count of outliers
  (ratio < 0.3 or > 3.0), a cheap signal of mis-links;
* match rate by year, so coverage gaps in time are visible.

``build_report`` returns a dict; ``format_report`` renders it as plain text for
the console or an exported ``match_quality_report.txt``.
"""

import statistics

# Salary-ratio band outside which a best match is flagged for review.
SALARY_RATIO_LOW = 0.3
SALARY_RATIO_HIGH = 3.0


def build_report(conn):
    cur = conn.cursor()

    def scalar(sql):
        return cur.execute(sql).fetchone()[0]

    total_execs = scalar(
        "SELECT COUNT(DISTINCT execid) FROM executive_year_panel")
    matched_execs = scalar(
        "SELECT COUNT(DISTINCT execid) FROM executive_year_panel "
        "WHERE user_id IS NOT NULL")

    tier_counts = dict(cur.execute(
        "SELECT tier, COUNT(*) FROM exec_revelio_link "
        "WHERE is_best = 1 AND accepted = 1 GROUP BY tier").fetchall())

    ambiguous_pairs = scalar(
        "SELECT COUNT(*) FROM (SELECT execid, gvkey FROM exec_revelio_link "
        "WHERE accepted = 1 GROUP BY execid, gvkey HAVING COUNT(*) > 1)")

    ratios = [r for (r,) in cur.execute(
        "SELECT salary_ratio FROM exec_revelio_link "
        "WHERE is_best = 1 AND accepted = 1 AND salary_ratio IS NOT NULL")]
    salary = None
    if ratios:
        salary = {
            "n": len(ratios),
            "min": round(min(ratios), 3),
            "median": round(statistics.median(ratios), 3),
            "max": round(max(ratios), 3),
            "n_outliers": sum(1 for r in ratios
                              if r < SALARY_RATIO_LOW or r > SALARY_RATIO_HIGH),
        }

    by_year = [
        (year, total, matched)
        for (year, total, matched) in cur.execute(
            "SELECT year, COUNT(DISTINCT execid), "
            "COUNT(DISTINCT CASE WHEN user_id IS NOT NULL THEN execid END) "
            "FROM executive_year_panel GROUP BY year ORDER BY year")
    ]

    return {
        "total_execs": total_execs,
        "matched_execs": matched_execs,
        "unmatched_execs": total_execs - matched_execs,
        "match_rate": round(matched_execs / total_execs, 4) if total_execs else None,
        "tier_counts": tier_counts,
        "ambiguous_pairs": ambiguous_pairs,
        "salary_ratio": salary,
        "by_year": by_year,
    }


def format_report(rep):
    lines = ["Match-quality report", "=" * 20]
    lines.append(
        f"Executives (NEOs)     : {rep['total_execs']} "
        f"({rep['matched_execs']} matched, {rep['unmatched_execs']} unmatched, "
        f"rate {rep['match_rate']})")
    tc = rep["tier_counts"]
    lines.append("Accepted by tier      : "
                 + ", ".join(f"{t}={tc.get(t, 0)}"
                             for t in ("high", "medium", "low")))
    lines.append(f"Ambiguous pairs       : {rep['ambiguous_pairs']} "
                 "(execid+gvkey with >1 accepted person -> review)")
    s = rep["salary_ratio"]
    if s:
        lines.append(
            f"Salary ratio (rev/exec): n={s['n']} min={s['min']} "
            f"median={s['median']} max={s['max']} outliers={s['n_outliers']}")
    else:
        lines.append("Salary ratio (rev/exec): n/a (no comparable salaries)")
    lines.append("Match rate by year    :")
    for year, total, matched in rep["by_year"]:
        rate = round(matched / total, 3) if total else 0
        lines.append(f"    {year}: {matched}/{total}  ({rate})")
    return "\n".join(lines)
