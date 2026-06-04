"""Export finished tables to CSV for use in Excel / Stata / R / pandas.

The pipeline's primary output is the SQLite database, but the analytical tables
are most convenient as flat files for downstream stats tools. This writes one
``.csv`` per requested table, with a header row and ``NULL`` rendered as an
empty cell. Standard library only (``csv``).
"""

import csv
import os

# Tables exported by default: the two deliverable panels, each matched
# executive's full work history, and the scored match/review table.
DEFAULT_EXPORT_TABLES = (
    "firm_year_panel",
    "executive_year_panel",
    "exec_work_history",
    "exec_mobility",
    "exec_revelio_link",
)


def export_tables(conn, export_dir, tables=DEFAULT_EXPORT_TABLES):
    """Write each table in ``tables`` to ``<export_dir>/<table>.csv``.

    Returns ``{table: (path, row_count)}``. Creates ``export_dir`` if needed.
    """
    os.makedirs(export_dir, exist_ok=True)
    results = {}
    for table in tables:
        path = os.path.join(export_dir, f"{table}.csv")
        cur = conn.execute(f"SELECT * FROM {table}")
        columns = [d[0] for d in cur.description]
        count = 0
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(columns)
            for row in cur:
                writer.writerow(["" if v is None else v for v in row])
                count += 1
        results[table] = (path, count)
    return results
