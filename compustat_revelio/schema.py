"""SQL schema for the combined Compustat + Revelio database.

The database is organised into three layers:

1. Raw source tables that mirror each provider as loaded from CSV:
   - ``compustat_fundamentals``  (firm-year financial fundamentals)
   - ``revelio_workforce``       (firm-year workforce / talent metrics)

2. A crosswalk that links the two sources at the company level:
   - ``company_crosswalk``       (gvkey  <->  rcid)

3. A merged analytical panel that joins everything into one firm-year table
   with a handful of derived metrics:
   - ``firm_year_panel``

Keeping the raw tables intact (rather than only storing the merged result)
means the link can be rebuilt or audited without re-ingesting the sources.
"""

# --- Raw source tables ------------------------------------------------------

COMPUSTAT_TABLE = """
CREATE TABLE compustat_fundamentals (
    gvkey     TEXT    NOT NULL,   -- Compustat permanent company id
    fyear     INTEGER NOT NULL,   -- fiscal year
    datadate  TEXT,               -- fiscal period end date (YYYY-MM-DD)
    tic       TEXT,               -- exchange ticker
    cusip     TEXT,               -- 9-character CUSIP
    conm      TEXT,               -- company name
    sale      REAL,               -- revenue, USD millions
    at        REAL,               -- total assets, USD millions
    ni        REAL,               -- net income, USD millions
    emp       REAL,               -- employees, thousands (as reported)
    naics     TEXT,               -- NAICS industry code
    sic       TEXT,               -- SIC industry code
    PRIMARY KEY (gvkey, fyear)
);
"""

REVELIO_TABLE = """
CREATE TABLE revelio_workforce (
    rcid           TEXT    NOT NULL,  -- Revelio company id
    company        TEXT,              -- company name (Revelio)
    year           INTEGER NOT NULL,  -- calendar year
    headcount      INTEGER,           -- estimated total headcount
    hires          INTEGER,           -- estimated hires during year
    departures     INTEGER,           -- estimated departures during year
    attrition_rate REAL,              -- departures / headcount
    avg_tenure     REAL,              -- average tenure, years
    avg_salary     REAL,              -- estimated average salary, USD
    ticker         TEXT,              -- mapped exchange ticker
    PRIMARY KEY (rcid, year)
);
"""

# --- Company-level crosswalk -----------------------------------------------

CROSSWALK_TABLE = """
CREATE TABLE company_crosswalk (
    gvkey            TEXT NOT NULL,  -- Compustat company
    rcid             TEXT NOT NULL,  -- Revelio company
    match_method     TEXT,           -- how the link was made (ticker/cusip/manual)
    match_confidence REAL,           -- 0-1 heuristic confidence score
    PRIMARY KEY (gvkey, rcid)
);
"""

# --- Merged firm-year analytical panel -------------------------------------

PANEL_TABLE = """
CREATE TABLE firm_year_panel (
    gvkey                     TEXT    NOT NULL,
    rcid                      TEXT,
    year                      INTEGER NOT NULL,
    conm                      TEXT,
    company                   TEXT,
    tic                       TEXT,
    cusip                     TEXT,
    naics                     TEXT,
    sic                       TEXT,
    -- Compustat financials
    sale                      REAL,
    at                        REAL,
    ni                        REAL,
    emp                       REAL,
    -- Revelio workforce
    headcount                 INTEGER,
    hires                     INTEGER,
    departures                INTEGER,
    attrition_rate            REAL,
    avg_tenure                REAL,
    avg_salary                REAL,
    -- Derived cross-source metrics
    revenue_per_employee_usd  REAL,   -- sale (USD) / Revelio headcount
    compustat_emp_count       REAL,   -- emp * 1000 (reported employees, headcount basis)
    headcount_coverage        REAL,   -- Revelio headcount / reported employees
    net_hiring                INTEGER, -- hires - departures
    -- Link provenance
    match_method              TEXT,
    match_confidence          REAL,
    PRIMARY KEY (gvkey, year)
);
"""

# Helpful indexes for typical query patterns.
INDEXES = [
    "CREATE INDEX idx_panel_year ON firm_year_panel (year);",
    "CREATE INDEX idx_panel_rcid ON firm_year_panel (rcid);",
    "CREATE INDEX idx_revelio_ticker ON revelio_workforce (ticker);",
    "CREATE INDEX idx_compustat_tic ON compustat_fundamentals (tic);",
]

# Order matters only in that we drop before create; creation order is independent.
ALL_TABLES = ["firm_year_panel", "company_crosswalk", "revelio_workforce",
              "compustat_fundamentals"]

CREATE_STATEMENTS = [COMPUSTAT_TABLE, REVELIO_TABLE, CROSSWALK_TABLE, PANEL_TABLE]
