"""CSV loaders for the Compustat, Execucomp and Revelio source files.

Each loader reads a delimited file and coerces every column to the type the
schema expects, so an empty cell becomes ``NULL`` rather than ``""`` and numeric
columns are stored as numbers. The column specs double as documentation of the
expected input format. Extra columns in a file are ignored; a missing expected
column raises a clear error.
"""

import csv


def _to_int(value):
    value = (value or "").strip()
    if value == "":
        return None
    # Tolerate "147000.0" style values from spreadsheet exports.
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

COMPUSTAT_FUNDA_COLUMNS = {
    "gvkey": _to_text,
    "fyear": _to_int,
    "datadate": _to_text,
    "tic": _to_text,
    "cusip": _to_text,
    "cik": _to_text,
    "conm": _to_text,
    "sale": _to_float,
    "at": _to_float,
    "ni": _to_float,
    "ceq": _to_float,
    "dltt": _to_float,
    "capx": _to_float,
    "xrd": _to_float,
    "emp": _to_float,
    "naics": _to_text,
    "sic": _to_text,
    "sich": _to_text,
}

INDEX_CONSTITUENTS_COLUMNS = {
    "gvkey": _to_text,
    "gvkeyx": _to_text,
    "conm": _to_text,
    "indexname": _to_text,
    "from_date": _to_text,
    "thru_date": _to_text,
}

EXECUCOMP_COLUMNS = {
    "gvkey": _to_text,
    "year": _to_int,
    "execid": _to_text,
    "co_per_rol": _to_text,
    "exec_fullname": _to_text,
    "exec_fname": _to_text,
    "exec_mname": _to_text,
    "exec_lname": _to_text,
    "coname": _to_text,
    "title": _to_text,
    "ceoann": _to_text,
    "cfoann": _to_text,
    "joined_co": _to_text,
    "leftco": _to_text,
    "salary": _to_float,
    "bonus": _to_float,
    "tdc1": _to_float,
    "tdc2": _to_float,
    "age": _to_int,
    "gender": _to_text,
}

REVELIO_INDIVIDUAL_COLUMNS = {
    "user_id": _to_text,
    "fullname": _to_text,
    "firstname": _to_text,
    "lastname": _to_text,
    "gender": _to_text,
    "ethnicity": _to_text,
}

REVELIO_POSITIONS_COLUMNS = {
    "position_id": _to_text,
    "user_id": _to_text,
    "rcid": _to_text,
    "company": _to_text,
    "position_number": _to_int,
    "role_raw": _to_text,
    "role_k150": _to_text,
    "role_k1500": _to_text,
    "job_category": _to_text,
    "seniority": _to_int,
    "salary": _to_float,
    "startdate": _to_text,
    "enddate": _to_text,
    "location": _to_text,
}

REVELIO_COMPANY_MAPPING_COLUMNS = {
    "rcid": _to_text,
    "company": _to_text,
    "ticker": _to_text,
    "cusip": _to_text,
    "isin": _to_text,
    "gvkey": _to_text,
    "lei": _to_text,
    "naics": _to_text,
    "sic": _to_text,
}


def load_rows(path, columns):
    """Read ``path`` as CSV and return a list of value tuples.

    ``columns`` is an ordered mapping of column name -> coercion function. Only
    the listed columns are read; extra columns are ignored. A missing expected
    column raises ``ValueError`` naming the offenders.
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
            rows.append(tuple(coerce(record.get(name))
                              for name, coerce in columns.items()))
    return rows


def load_compustat_funda(path):
    return load_rows(path, COMPUSTAT_FUNDA_COLUMNS)


# Constituent-list columns are all optional (a row needs at least one of
# ticker / cik / gvkey to be resolvable), so this loader tolerates any subset.
CONSTITUENTS_COLUMNS = {
    "ticker": _to_text,
    "company": _to_text,
    "cik": _to_text,
    "gvkey": _to_text,
    "index_name": _to_text,
    "from_year": _to_int,
    "thru_year": _to_int,
}


def load_constituents(path):
    """Read a constituent-list CSV; missing optional columns become NULL."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = set(reader.fieldnames or [])
        if not ({"ticker", "cik", "gvkey"} & fields):
            raise ValueError(
                f"{path} must contain at least one of: ticker, cik, gvkey")
        for record in reader:
            rows.append(tuple(
                coerce(record.get(name)) for name, coerce in CONSTITUENTS_COLUMNS.items()))
    return rows


def load_index_constituents(path):
    return load_rows(path, INDEX_CONSTITUENTS_COLUMNS)


def load_execucomp(path):
    return load_rows(path, EXECUCOMP_COLUMNS)


def load_revelio_individual(path):
    return load_rows(path, REVELIO_INDIVIDUAL_COLUMNS)


def load_revelio_positions(path):
    return load_rows(path, REVELIO_POSITIONS_COLUMNS)


def load_revelio_company_mapping(path):
    return load_rows(path, REVELIO_COMPANY_MAPPING_COLUMNS)
