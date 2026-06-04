"""CSV loaders for the Compustat and Revelio source files.

Each loader reads a delimited file and coerces every column to the type the
schema expects, so that an empty cell becomes ``NULL`` rather than an empty
string and numeric columns are stored as numbers. The column specs double as
documentation of the expected input format.
"""

import csv


def _to_int(value):
    value = (value or "").strip()
    if value == "":
        return None
    # Tolerate values that arrive as "147000.0" from spreadsheet exports.
    return int(float(value))


def _to_float(value):
    value = (value or "").strip()
    if value == "":
        return None
    return float(value)


def _to_text(value):
    value = (value or "").strip()
    return value or None


# Column name -> coercion function. Order defines the INSERT column order.
COMPUSTAT_COLUMNS = {
    "gvkey": _to_text,
    "fyear": _to_int,
    "datadate": _to_text,
    "tic": _to_text,
    "cusip": _to_text,
    "conm": _to_text,
    "sale": _to_float,
    "at": _to_float,
    "ni": _to_float,
    "emp": _to_float,
    "naics": _to_text,
    "sic": _to_text,
}

REVELIO_COLUMNS = {
    "rcid": _to_text,
    "company": _to_text,
    "year": _to_int,
    "headcount": _to_int,
    "hires": _to_int,
    "departures": _to_int,
    "attrition_rate": _to_float,
    "avg_tenure": _to_float,
    "avg_salary": _to_float,
    "ticker": _to_text,
}


def load_rows(path, columns):
    """Read ``path`` as CSV and return a list of value tuples.

    ``columns`` is an ordered mapping of column name -> coercion function.
    Only the listed columns are read; any extra columns in the file are
    ignored, and any missing column is treated as empty (-> NULL).
    """
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"{path} is missing expected columns: {', '.join(missing)}"
            )
        for record in reader:
            rows.append(tuple(coerce(record.get(name)) for name, coerce in columns.items()))
    return rows


def load_compustat(path):
    return load_rows(path, COMPUSTAT_COLUMNS)


def load_revelio(path):
    return load_rows(path, REVELIO_COLUMNS)
