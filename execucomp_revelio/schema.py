"""SQL schema for the Execucomp + Compustat + Revelio executive panel.

Three layers, mirroring the firm-level ``compustat_revelio`` module:

1. Raw source tables (one per WRDS extract, loaded verbatim with typing):
   - ``compustat_funda``          Compustat annual fundamentals  (gvkey x fyear)
   - ``compustat_index_constituents``  S&P index history         (idxcst_his)
   - ``execucomp_anncomp``        Execucomp annual compensation  (exec x year)
   - ``revelio_individual``       Revelio person master          (user_id)
   - ``revelio_positions``        Revelio work-history spells    (position_id)
   - ``revelio_company_mapping``  Revelio company id crosswalk   (rcid)

2. Derived linking / filtering tables:
   - ``universe_firm_year``       S&P 1000, in-window, ex-SIC firm-years
   - ``company_crosswalk``        gvkey <-> rcid (from Revelio's gvkey)
   - ``exec_revelio_link``        Execucomp exec <-> Revelio user, scored/tiered
   - ``exec_work_history``        complete Revelio career history of matched execs

3. Two merged analytical panels (the deliverables):
   - ``firm_year_panel``          gvkey x year
   - ``executive_year_panel``     execid x gvkey x year
"""

# --- Raw source tables ------------------------------------------------------

COMPUSTAT_FUNDA_TABLE = """
CREATE TABLE compustat_funda (
    gvkey     TEXT    NOT NULL,   -- Compustat permanent company id
    fyear     INTEGER NOT NULL,   -- fiscal year
    datadate  TEXT,               -- fiscal period end date (YYYY-MM-DD)
    tic       TEXT,               -- exchange ticker
    cusip     TEXT,               -- 9-character CUSIP
    conm      TEXT,               -- company name
    sale      REAL,               -- revenue, USD millions
    at        REAL,               -- total assets, USD millions
    ni        REAL,               -- net income, USD millions
    ceq       REAL,               -- common/ordinary equity, USD millions
    dltt      REAL,               -- long-term debt, USD millions
    capx      REAL,               -- capital expenditures, USD millions
    xrd       REAL,               -- R&D expense, USD millions
    emp       REAL,               -- employees, thousands (as reported)
    naics     TEXT,               -- NAICS industry code
    sic       TEXT,               -- header SIC industry code
    sich      TEXT,               -- historical SIC industry code (preferred)
    PRIMARY KEY (gvkey, fyear)
);
"""

INDEX_CONSTITUENTS_TABLE = """
CREATE TABLE compustat_index_constituents (
    gvkey     TEXT NOT NULL,   -- constituent company
    gvkeyx    TEXT NOT NULL,   -- index id (e.g. S&P MidCap 400 / SmallCap 600)
    conm      TEXT,            -- constituent company name
    indexname TEXT,            -- index name, if provided
    from_date TEXT,            -- membership start date (YYYY-MM-DD)
    thru_date TEXT             -- membership end date (YYYY-MM-DD), NULL if current
);
"""

EXECUCOMP_TABLE = """
CREATE TABLE execucomp_anncomp (
    gvkey         TEXT    NOT NULL,  -- company (links to Compustat)
    year          INTEGER NOT NULL,  -- fiscal year of the comp record
    execid        TEXT    NOT NULL,  -- Execucomp permanent executive id
    co_per_rol    TEXT,              -- company-person-role id
    exec_fullname TEXT,              -- executive full name (as reported)
    exec_fname    TEXT,              -- first name
    exec_mname    TEXT,              -- middle name/initial
    exec_lname    TEXT,              -- last name
    coname        TEXT,              -- company name
    title         TEXT,              -- reported title
    ceoann        TEXT,              -- 'CEO' if person was annual CEO, else NULL
    cfoann        TEXT,              -- 'CFO' if person was annual CFO, else NULL
    joined_co     TEXT,              -- date joined company (YYYY-MM-DD)
    leftco        TEXT,              -- date left company (YYYY-MM-DD)
    salary        REAL,              -- base salary, USD thousands
    bonus         REAL,              -- bonus, USD thousands
    tdc1          REAL,              -- total comp (incl. option grants), USD thousands
    tdc2          REAL,              -- total comp (incl. options exercised), USD thousands
    age           INTEGER,           -- executive age
    gender        TEXT,              -- reported gender
    PRIMARY KEY (gvkey, year, execid)
);
"""

REVELIO_INDIVIDUAL_TABLE = """
CREATE TABLE revelio_individual (
    user_id   TEXT NOT NULL,   -- Revelio unique person id
    fullname  TEXT,            -- name reported on profile
    firstname TEXT,            -- parsed first name
    lastname  TEXT,            -- parsed last name
    gender    TEXT,            -- modeled gender
    ethnicity TEXT,            -- modeled ethnicity
    PRIMARY KEY (user_id)
);
"""

REVELIO_POSITIONS_TABLE = """
CREATE TABLE revelio_positions (
    position_id     TEXT NOT NULL,  -- Revelio position id
    user_id         TEXT NOT NULL,  -- person holding the position
    rcid            TEXT,           -- Revelio company id
    company         TEXT,           -- company name (Revelio)
    position_number INTEGER,        -- chronological order in the person's profile
    role_raw        TEXT,           -- raw role/title text, if available
    role_k150       TEXT,           -- role taxonomy (150 levels)
    role_k1500      TEXT,           -- role taxonomy (1500 levels)
    seniority       INTEGER,        -- ordinal seniority 1-7
    salary          REAL,           -- modeled annual salary, USD
    startdate       TEXT,           -- position start date (YYYY-MM-DD), may be NULL
    enddate         TEXT,           -- position end date (YYYY-MM-DD), NULL if current
    location        TEXT,           -- position location
    PRIMARY KEY (position_id)
);
"""

REVELIO_COMPANY_MAPPING_TABLE = """
CREATE TABLE revelio_company_mapping (
    rcid    TEXT NOT NULL,   -- Revelio company id
    company TEXT,            -- Revelio primary company name
    ticker  TEXT,            -- mapped exchange ticker
    cusip   TEXT,            -- mapped CUSIP
    isin    TEXT,            -- mapped ISIN
    gvkey   TEXT,            -- mapped Compustat gvkey (the primary link key)
    lei     TEXT,            -- Legal Entity Identifier
    naics   TEXT,            -- NAICS industry code
    sic     TEXT,            -- SIC industry code
    PRIMARY KEY (rcid)
);
"""

# --- Derived linking / filtering tables ------------------------------------

UNIVERSE_TABLE = """
CREATE TABLE universe_firm_year (
    gvkey         TEXT    NOT NULL,
    year          INTEGER NOT NULL,
    conm          TEXT,
    sic_used      TEXT,            -- the SIC actually used (sich or sic)
    index_member  TEXT,            -- which S&P index code(s) it belonged to
    PRIMARY KEY (gvkey, year)
);
"""

CROSSWALK_TABLE = """
CREATE TABLE company_crosswalk (
    gvkey            TEXT NOT NULL,  -- Compustat / Execucomp company
    rcid             TEXT NOT NULL,  -- Revelio company
    match_method     TEXT,           -- 'revelio_gvkey' / 'ticker' / 'cusip'
    match_confidence REAL,           -- 0-1 heuristic confidence
    PRIMARY KEY (gvkey, rcid)
);
"""

EXEC_LINK_TABLE = """
CREATE TABLE exec_revelio_link (
    execid        TEXT NOT NULL,  -- Execucomp executive
    gvkey         TEXT NOT NULL,  -- company the match was scoped to
    user_id       TEXT NOT NULL,  -- candidate Revelio person
    position_id   TEXT,           -- the corroborating Revelio position at gvkey
    rcid          TEXT,           -- Revelio company of that position
    exec_name     TEXT,           -- Execucomp name (for review)
    revelio_name  TEXT,           -- Revelio name (for review)
    name_score    REAL,           -- 0-1 name similarity
    seniority_ok  INTEGER,        -- 1 if the position is executive-level
    role_ok       INTEGER,        -- 1 if a role keyword matched
    date_overlap  INTEGER,        -- 1 if tenure windows overlap
    salary_ratio  REAL,           -- revelio salary / execucomp salary (sanity check)
    total_score   REAL,           -- weighted match score
    tier          TEXT,           -- 'high' / 'medium' / 'low'
    accepted      INTEGER,        -- 1 if tier >= acceptance threshold
    is_best       INTEGER,        -- 1 if best accepted candidate for (execid, gvkey)
    PRIMARY KEY (execid, gvkey, user_id)
);
"""

WORK_HISTORY_TABLE = """
CREATE TABLE exec_work_history (
    execid          TEXT NOT NULL,  -- Execucomp executive this history belongs to
    user_id         TEXT NOT NULL,  -- matched Revelio person
    position_id     TEXT NOT NULL,  -- a position spell in that person's profile
    position_number INTEGER,        -- chronological order
    rcid            TEXT,           -- Revelio company of the spell
    company         TEXT,           -- company name
    gvkey           TEXT,           -- Compustat gvkey of the company, if mapped
    role_raw        TEXT,           -- raw role/title
    role_k150       TEXT,           -- role taxonomy (150 levels)
    seniority       INTEGER,        -- ordinal seniority 1-7
    salary          REAL,           -- modeled annual salary, USD
    startdate       TEXT,           -- spell start (YYYY-MM-DD)
    enddate         TEXT,           -- spell end (YYYY-MM-DD), NULL if current
    PRIMARY KEY (execid, user_id, position_id)
);
"""

# --- Merged analytical panels ----------------------------------------------

FIRM_YEAR_PANEL_TABLE = """
CREATE TABLE firm_year_panel (
    gvkey                 TEXT    NOT NULL,
    rcid                  TEXT,
    year                  INTEGER NOT NULL,
    conm                  TEXT,
    sic_used              TEXT,
    -- Compustat financials
    sale                  REAL,
    at                    REAL,
    ni                    REAL,
    ceq                   REAL,
    dltt                  REAL,
    capx                  REAL,
    xrd                   REAL,
    emp                   REAL,
    -- Execucomp aggregates over the firm's NEOs
    n_neos                INTEGER,   -- # named executives in the firm-year
    ceo_execid            TEXT,      -- execid of the annual CEO
    ceo_tdc1              REAL,      -- CEO total comp (TDC1), USD thousands
    neo_total_tdc1        REAL,      -- sum of NEO TDC1, USD thousands
    -- Revelio (matched executives at this firm-year)
    n_neos_revelio_matched INTEGER,  -- # NEOs linked to a Revelio person
    avg_exec_modeled_salary REAL,    -- mean Revelio modeled salary of matched NEOs, USD
    PRIMARY KEY (gvkey, year)
);
"""

EXECUTIVE_YEAR_PANEL_TABLE = """
CREATE TABLE executive_year_panel (
    execid            TEXT    NOT NULL,
    gvkey             TEXT    NOT NULL,
    year              INTEGER NOT NULL,
    exec_fullname     TEXT,
    coname            TEXT,
    title             TEXT,
    is_ceo            INTEGER,   -- 1 if annual CEO
    is_cfo            INTEGER,   -- 1 if annual CFO
    -- Execucomp compensation
    salary            REAL,      -- base salary, USD thousands
    bonus             REAL,      -- bonus, USD thousands
    tdc1              REAL,      -- total comp, USD thousands
    -- Revelio link + that year's modeled position
    user_id           TEXT,      -- matched Revelio person (NULL if unmatched)
    match_tier        TEXT,      -- 'high'/'medium'/'low'
    match_score       REAL,
    revelio_seniority INTEGER,   -- seniority of the Revelio position active that year
    revelio_role      TEXT,      -- role of that position
    revelio_salary    REAL,      -- Revelio modeled annual salary, USD
    PRIMARY KEY (execid, gvkey, year)
);
"""

# Helpful indexes for typical query patterns.
INDEXES = [
    "CREATE INDEX idx_funda_fyear ON compustat_funda (fyear);",
    "CREATE INDEX idx_idxcst_gvkeyx ON compustat_index_constituents (gvkeyx);",
    "CREATE INDEX idx_anncomp_gvkey_year ON execucomp_anncomp (gvkey, year);",
    "CREATE INDEX idx_positions_user ON revelio_positions (user_id);",
    "CREATE INDEX idx_positions_rcid ON revelio_positions (rcid);",
    "CREATE INDEX idx_mapping_gvkey ON revelio_company_mapping (gvkey);",
    "CREATE INDEX idx_link_user ON exec_revelio_link (user_id);",
    "CREATE INDEX idx_workhist_user ON exec_work_history (user_id);",
    "CREATE INDEX idx_fpanel_year ON firm_year_panel (year);",
    "CREATE INDEX idx_epanel_year ON executive_year_panel (year);",
]

# Drop order (children before parents not required for SQLite, but keep tidy).
ALL_TABLES = [
    "executive_year_panel", "firm_year_panel",
    "exec_work_history", "exec_revelio_link", "company_crosswalk",
    "universe_firm_year",
    "revelio_company_mapping", "revelio_positions", "revelio_individual",
    "execucomp_anncomp", "compustat_index_constituents", "compustat_funda",
]

CREATE_STATEMENTS = [
    COMPUSTAT_FUNDA_TABLE, INDEX_CONSTITUENTS_TABLE, EXECUCOMP_TABLE,
    REVELIO_INDIVIDUAL_TABLE, REVELIO_POSITIONS_TABLE,
    REVELIO_COMPANY_MAPPING_TABLE,
    UNIVERSE_TABLE, CROSSWALK_TABLE, EXEC_LINK_TABLE, WORK_HISTORY_TABLE,
    FIRM_YEAR_PANEL_TABLE, EXECUTIVE_YEAR_PANEL_TABLE,
]
