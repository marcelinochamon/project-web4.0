"""Self-contained build pipeline (auto-assembled from execucomp_revelio).

Reads the six WRDS CSVs and writes the SQLite DB + panels/exports.
Run with no args (defaults to ./wrds_csv -> ./out):  python standalone.py
"""


# ===== config.py =====
"""Tunable parameters for the Execucomp + Compustat + Revelio pipeline.

Everything a user is likely to want to change for their own WRDS extracts lives
here (or is exposed as a CLI flag in ``build_database.py``). Nothing in this
file is secret or environment-specific.
"""

# --- Sample / universe window ----------------------------------------------

# Fiscal-year range kept in the panel (inclusive). The user's study window.
MIN_FYEAR = 2009
MAX_FYEAR = 2019


# --- S&P 1000 membership ----------------------------------------------------

# The S&P 1000 = S&P MidCap 400 + S&P SmallCap 600. In Compustat ``idxcst_his``
# each index is identified by a ``gvkeyx``. These are the confirmed WRDS codes
# (from ``comp.idx_index``): S&P MidCap 400 = 024248, S&P SmallCap 600 = 030824
# (a direct "S&P 1000 Index" also exists as 146884). Override via
# ``--index-gvkeyx`` if your environment differs.
SP1000_INDEX_GVKEYX = ("024248", "030824")


# --- SIC industry exclusions ------------------------------------------------

# Inclusive SIC code ranges to drop from the  Default per the user's
# choice: financials (6000-6999) and utilities (4900-4949). The historical SIC
# (``sich``) is used when present, falling back to the header ``sic``.
EXCLUDED_SIC_RANGES = (
    (6000, 6999),   # Finance, insurance, real estate
    (4900, 4949),   # Electric, gas & sanitary utilities
)


# --- Executive <-> Revelio matching -----------------------------------------

# Revelio seniority is a 1-7 ordinal scale; a position at or above this level is
# treated as an "executive" position for the seniority signal.
EXEC_SENIORITY_MIN = 6

# Optional keywords used to flag an executive role when a raw role/title string
# is available on the Revelio positions file (column ``role_raw``). The role
# taxonomy codes (``role_k*``) are kept as data but not hard-coded here.
EXEC_ROLE_KEYWORDS = (
    "chief", "president", "ceo", "cfo", "coo", "cto", "cio",
    "executive vice president", "evp", "head of", "managing director",
)

# Name-similarity thresholds (see names.name_score, range 0-1).
NAME_STRONG = 0.90   # confident same-person name
NAME_WEAK = 0.70     # plausible same-person name (e.g. last + first initial)

# Score weights. total_score = name*W_NAME + seniority_ok*W_SENIORITY
#                              + date_overlap*W_DATE   (max 1.0)
W_NAME = 0.60
W_SENIORITY = 0.20
W_DATE = 0.20

# Acceptance tiers, from the strongest signal combination to the weakest:
#   high   - strong name + same company + (executive seniority OR date overlap)
#   medium - strong name + same company (no corroborating signal) OR
#            weak name  + same company + (seniority OR date overlap)
#   low    - weak name  + same company only
# The default accept threshold ("medium") is the balanced setting; relax to
# "low" for lenient or tighten to "high" for strict via ``--min-tier``.
TIER_ORDER = ("low", "medium", "high")
DEFAULT_MIN_TIER = "medium"

# ===== jobcat.py =====
"""The 7-value job-category variable (Revelio's top-level ``role_k7`` taxonomy).

Every Revelio position maps to one of seven broad job families. We normalise
whatever label/spelling the source provides to a fixed canonical set so the
variable always takes one of exactly these seven values (or ``None`` when a
position has no role information).
"""

# Canonical values, in the order requested.
CATEGORIES = ("admin", "finance", "marketing", "sales", "operations",
              "scientist", "engineer")

# Source spellings -> canonical value. Revelio's role_k7 labels map directly;
# common synonyms are included so other vintages/exports still resolve.
_SYNONYMS = {
    "admin": "admin", "administrative": "admin", "administration": "admin",
    "administrator": "admin",
    "finance": "finance", "financial": "finance", "accounting": "finance",
    "marketing": "marketing",
    "sales": "sales",
    "operations": "operations", "operation": "operations", "ops": "operations",
    "scientist": "scientist", "science": "scientist", "scientific": "scientist",
    "research": "scientist",
    "engineer": "engineer", "engineering": "engineer",
}


def normalize(value):
    """Return the canonical job category for ``value``, or ``None``."""
    if value is None:
        return None
    key = str(value).strip().lower()
    if key in CATEGORIES:
        return key
    return _SYNONYMS.get(key)


def primary(pairs):
    """Pick a single 'primary' category from ``(category, seniority)`` pairs.

    The category of the highest-seniority position in a career (ties broken by
    the canonical order). Returns ``None`` if nothing resolves.
    """
    best = None
    for category, seniority in pairs:
        cat = normalize(category)
        if cat is None:
            continue
        rank = (seniority or 0, -CATEGORIES.index(cat))
        if best is None or rank > best[0]:
            best = (rank, cat)
    return best[1] if best else None

# ===== names.py =====
"""Person-name normalization and similarity scoring.

Executive names arrive in two shapes -- Execucomp gives first/middle/last parts
(and a full name), Revelio gives first/last (and a full name). We reduce both to
a canonical ``(first, last, tokens)`` form and score similarity on a 0-1 scale
so the matcher can threshold it. Pure standard library (``unicodedata``, ``re``).
"""

import re
import unicodedata

# Generational/honorific tokens that should not affect identity.
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "hon"}
_DROP = _SUFFIXES | _TITLES

_NONALPHA = re.compile(r"[^a-z\s]+")


def _strip_accents(text):
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalize_tokens(*parts):
    """Return a list of lowercase alphabetic name tokens from ``parts``.

    Accepts any mix of full names and individual name pieces. Honorifics and
    generational suffixes are dropped; punctuation and accents are stripped.
    """
    text = " ".join(p for p in parts if p)
    text = _strip_accents(text).lower()
    text = _NONALPHA.sub(" ", text)
    tokens = [t for t in text.split() if t and t not in _DROP]
    return tokens


def canonical(first=None, middle=None, last=None, full=None):
    """Build a canonical name dict from whatever pieces are available.

    Prefers explicit first/last parts; falls back to parsing ``full`` (treating
    the last token as the surname). Returns ``{'first','last','tokens'}`` with a
    de-duplicated, order-independent token set for robust comparison.
    """
    first_t = normalize_tokens(first)
    last_t = normalize_tokens(last)

    if not (first_t or last_t) and full:
        parsed = normalize_tokens(full)
        if parsed:
            last_t = [parsed[-1]]
            first_t = parsed[:1]

    all_tokens = normalize_tokens(first, middle, last, full)
    return {
        "first": first_t[0] if first_t else None,
        "last": last_t[-1] if last_t else None,
        "tokens": frozenset(all_tokens),
    }


def _initial(token):
    return token[0] if token else None


def name_score(a, b):
    """Return a 0-1 similarity between two canonical names from ``canonical``.

    Scale:
      1.00  identical token sets (same name, ignoring order/middle)
      0.95  same first AND same last name
      0.85  same last name + same first initial (first names differ in length)
      0.70  same last name only, or Jaccard-equivalent partial overlap
      <0.70 weaker token overlap (Jaccard), down to 0.0
    """
    ta, tb = a["tokens"], b["tokens"]
    if not ta or not tb:
        return 0.0

    if ta == tb:
        return 1.0

    same_last = a["last"] and a["last"] == b["last"]
    if same_last and a["first"] and a["first"] == b["first"]:
        return 0.95
    if same_last and _initial(a["first"]) and _initial(a["first"]) == _initial(b["first"]):
        # e.g. "Robert" vs "Rob", "R." -- same surname, same first initial.
        return 0.85

    # Token Jaccard as a graceful fallback; nudge up a notch if surnames match.
    jaccard = len(ta & tb) / len(ta | tb)
    if same_last:
        return max(0.70, jaccard)
    return round(jaccard, 4)

# ===== schema.py =====
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
    cik       TEXT,               -- SEC Central Index Key
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
    job_category    TEXT,           -- 7-value job family (Revelio role_k7)
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

# --- Optional explicit constituent list (alternative to idxcst_his) --------

CONSTITUENTS_TABLE = """
CREATE TABLE constituents_list (
    ticker     TEXT,            -- exchange ticker (resolves to gvkey via funda.tic)
    company    TEXT,            -- company name (for audit)
    cik        TEXT,            -- SEC CIK (resolves to gvkey via funda.cik; preferred)
    gvkey      TEXT,            -- gvkey if already known (used directly)
    index_name TEXT,            -- which index the row belongs to (e.g. SP400MidCap)
    from_year  INTEGER,         -- first membership year, if known (else all years)
    thru_year  INTEGER          -- last membership year, if known (else all years)
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
    job_category    TEXT,           -- 7-value job family (admin/finance/...)
    seniority       INTEGER,        -- ordinal seniority 1-7
    salary          REAL,           -- modeled annual salary, USD
    startdate       TEXT,           -- spell start (YYYY-MM-DD)
    enddate         TEXT,           -- spell end (YYYY-MM-DD), NULL if current
    PRIMARY KEY (execid, user_id, position_id)
);
"""

MOBILITY_TABLE = """
CREATE TABLE exec_mobility (
    execid                       TEXT NOT NULL,  -- Execucomp executive
    user_id                      TEXT NOT NULL,  -- matched Revelio person
    n_positions                  INTEGER,  -- total Revelio position spells
    n_employers                  INTEGER,  -- distinct companies (rcid) worked at
    max_seniority                INTEGER,  -- highest seniority reached (1-7)
    n_exec_positions             INTEGER,  -- spells at executive seniority
    primary_job_category         TEXT,     -- job family of the top-seniority role
    career_start_year            INTEGER,  -- earliest position start year
    career_end_year              INTEGER,  -- latest end year (ref year if ongoing)
    experience_years             INTEGER,  -- career_end_year - career_start_year
    n_prior_employers_before_focal INTEGER, -- distinct employers before the focal firm
    internal_promotion           INTEGER,  -- 1 = rose to exec inside the focal firm
    external_hire                INTEGER,  -- 1 = entered focal firm at exec level from outside
    PRIMARY KEY (execid, user_id)
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
    revelio_job_category TEXT,   -- 7-value job family of that position
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
    "CREATE INDEX idx_mobility_user ON exec_mobility (user_id);",
    "CREATE INDEX idx_fpanel_year ON firm_year_panel (year);",
    "CREATE INDEX idx_epanel_year ON executive_year_panel (year);",
]

# Drop order (children before parents not required for SQLite, but keep tidy).
ALL_TABLES = [
    "executive_year_panel", "firm_year_panel", "exec_mobility",
    "exec_work_history", "exec_revelio_link", "company_crosswalk",
    "universe_firm_year", "constituents_list",
    "revelio_company_mapping", "revelio_positions", "revelio_individual",
    "execucomp_anncomp", "compustat_index_constituents", "compustat_funda",
]

CREATE_STATEMENTS = [
    COMPUSTAT_FUNDA_TABLE, INDEX_CONSTITUENTS_TABLE, EXECUCOMP_TABLE,
    REVELIO_INDIVIDUAL_TABLE, REVELIO_POSITIONS_TABLE,
    REVELIO_COMPANY_MAPPING_TABLE, CONSTITUENTS_TABLE,
    UNIVERSE_TABLE, CROSSWALK_TABLE, EXEC_LINK_TABLE, WORK_HISTORY_TABLE,
    MOBILITY_TABLE, FIRM_YEAR_PANEL_TABLE, EXECUTIVE_YEAR_PANEL_TABLE,
]

# ===== loaders.py =====
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

# ===== universe.py =====
"""Build the firm-year universe: S&P 1000, in study window, ex excluded SIC.

The universe is the spine onto which Execucomp and Revelio are merged. A
Compustat firm-year (``gvkey``, ``fyear``) is kept when all three hold:

1. **Window**   - ``MIN_FYEAR <= fyear <= MAX_FYEAR``.
2. **S&P 1000** - the firm was a constituent of one of the configured S&P index
   codes (MidCap 400 + SmallCap 600) at some point during that fiscal year,
   per ``compustat_index_constituents`` (idxcst_his) date ranges.
3. **Industry** - its SIC (historical ``sich`` preferred, else header ``sic``)
   does not fall in any excluded range (financials & utilities by default).

Membership is evaluated on the fiscal *year* (calendar-year overlap of the
``from_date``/``thru_date`` window) rather than exact dates, which is robust to
the date formats WRDS exports use and to fiscal-year-end variation.
"""


def _year_of(date_text):
    """Extract the 4-digit year from a 'YYYY-...' date string, or None."""
    if not date_text:
        return None
    head = date_text.strip()[:4]
    return int(head) if head.isdigit() else None


def _sic_excluded(sic_text, excluded_ranges):
    if not sic_text:
        return False
    digits = sic_text.strip()[:4]
    if not digits.isdigit():
        return False
    code = int(digits)
    return any(lo <= code <= hi for lo, hi in excluded_ranges)


def _membership_by_year(index_rows, index_gvkeyx):
    """Map gvkey -> {year: set(gvkeyx)} for the configured index codes.

    A membership row contributes its index code to every calendar year its
    [from_date, thru_date] window spans. An open (NULL) ``thru_date`` is treated
    as current and extended to a far-future sentinel.
    """
    wanted = set(index_gvkeyx)
    membership = {}
    for gvkey, gvkeyx, _conm, _indexname, from_date, thru_date in index_rows:
        if gvkeyx not in wanted:
            continue
        start = _year_of(from_date) or 1900
        end = _year_of(thru_date) or 9999
        per_year = membership.setdefault(gvkey, {})
        for year in range(start, end + 1):
            per_year.setdefault(year, set()).add(gvkeyx)
    return membership


def _norm_cik(value):
    """Normalise a CIK to its integer string form (drops zero-padding)."""
    if not value:
        return None
    digits = value.strip().lstrip("0")
    return digits or "0" if value.strip().isdigit() else None


def _funda_lookups(cur):
    """Return (gvkeys, tic->gvkeys, cik->gvkeys, (gvkey,year)->(conm, sic))."""
    gvkeys, tic_map, cik_map, info = set(), {}, {}, {}
    for gvkey, fyear, tic, cik, conm, sic, sich in cur.execute(
            "SELECT gvkey, fyear, tic, cik, conm, sic, sich FROM compustat_funda"):
        gvkeys.add(gvkey)
        if tic:
            tic_map.setdefault(tic.strip().upper(), set()).add(gvkey)
        nc = _norm_cik(cik)
        if nc:
            cik_map.setdefault(nc, set()).add(gvkey)
        if fyear is not None:
            info[(gvkey, fyear)] = (conm, sich or sic)
    return gvkeys, tic_map, cik_map, info


def build_universe_from_list(conn, min_fyear, max_fyear, excluded_ranges):
    """Build ``universe_firm_year`` from ``constituents_list`` instead of idxcst.

    Resolves each constituent to a Compustat ``gvkey`` (preferring an explicit
    gvkey, then CIK, then ticker), then keeps the firm-years that exist in
    ``compustat_funda``, fall in the window, and pass the SIC filter. Returns
    ``(kept_rows, stats)`` where ``stats`` reports how rows resolved.
    """
    cur = conn.cursor()
    gvkeys, tic_map, cik_map, info = _funda_lookups(cur)

    rows = cur.execute(
        "SELECT ticker, company, cik, gvkey, index_name, from_year, thru_year "
        "FROM constituents_list").fetchall()

    stats = {"constituents": len(rows), "by_gvkey": 0, "by_cik": 0,
             "by_ticker": 0, "unresolved": 0, "ambiguous": 0}
    kept = {}  # (gvkey, year) -> [conm, sic_used, set(index labels)]

    for ticker, company, cik, gvkey, index_name, from_year, thru_year in rows:
        resolved, method = set(), None
        gk = (gvkey or "").strip()
        if gk and gk in gvkeys:
            resolved, method = {gk}, "by_gvkey"
        else:
            nc = _norm_cik(cik)
            if nc and nc in cik_map:
                resolved, method = cik_map[nc], "by_cik"
            elif ticker and ticker.strip().upper() in tic_map:
                resolved, method = tic_map[ticker.strip().upper()], "by_ticker"

        if not resolved:
            stats["unresolved"] += 1
            continue
        stats[method] += 1
        if len(resolved) > 1:
            stats["ambiguous"] += 1

        lo = max(from_year or min_fyear, min_fyear)
        hi = min(thru_year or max_fyear, max_fyear)
        label = index_name or method
        for g in resolved:
            for year in range(lo, hi + 1):
                meta = info.get((g, year))
                if meta is None:
                    continue  # no fundamentals that year -> can't place it
                conm, sic_used = meta
                if _sic_excluded(sic_used, excluded_ranges):
                    continue
                entry = kept.setdefault((g, year), [conm, sic_used, set()])
                entry[2].add(label)

    kept_rows = [(g, y, conm, sic_used, "+".join(sorted(labels)))
                 for (g, y), (conm, sic_used, labels) in sorted(kept.items())]

    cur.execute("DELETE FROM universe_firm_year;")
    cur.executemany(
        "INSERT INTO universe_firm_year (gvkey, year, conm, sic_used, index_member) "
        "VALUES (?, ?, ?, ?, ?);",
        kept_rows,
    )
    conn.commit()
    return kept_rows, stats


def build_universe(conn, index_gvkeyx, min_fyear, max_fyear, excluded_ranges):
    """Compute and load ``universe_firm_year``; return the list of kept rows."""
    cur = conn.cursor()

    index_rows = cur.execute(
        "SELECT gvkey, gvkeyx, conm, indexname, from_date, thru_date "
        "FROM compustat_index_constituents"
    ).fetchall()
    membership = _membership_by_year(index_rows, index_gvkeyx)

    funda_rows = cur.execute(
        "SELECT gvkey, fyear, conm, sic, sich FROM compustat_funda"
    ).fetchall()

    kept = []
    for gvkey, fyear, conm, sic, sich in funda_rows:
        if fyear is None or not (min_fyear <= fyear <= max_fyear):
            continue
        member_codes = membership.get(gvkey, {}).get(fyear)
        if not member_codes:
            continue
        sic_used = sich or sic
        if _sic_excluded(sic_used, excluded_ranges):
            continue
        kept.append((gvkey, fyear, conm, sic_used, "+".join(sorted(member_codes))))

    cur.execute("DELETE FROM universe_firm_year;")
    cur.executemany(
        "INSERT INTO universe_firm_year (gvkey, year, conm, sic_used, index_member) "
        "VALUES (?, ?, ?, ?, ?);",
        kept,
    )
    conn.commit()
    return kept

# ===== crosswalk.py =====
"""Build the company crosswalk (gvkey <-> rcid).

Unlike the firm-level ``compustat_revelio`` module, here the link is *given*:
Revelio's company-mapping file carries ``gvkey`` directly, so the primary link
is a straight join on ``gvkey``. Ticker and CUSIP are only fallbacks for the
rare ``rcid`` whose mapping row lacks a ``gvkey``.

The relationship is intentionally many-to-many: a single Compustat ``gvkey`` can
correspond to several Revelio ``rcid`` entities (subsidiaries, rebrandings), and
we want positions at *any* of them when assembling an executive's tenure.
"""


def _clean(value):
    return (value or "").strip().upper() or None


def _cusip8(value):
    v = _clean(value)
    return v[:8] if v else None


def build_crosswalk(conn):
    """Compute and load ``company_crosswalk``; return the link tuples.

    Only ``gvkey`` values that actually appear in Compustat fundamentals are
    linked, so the crosswalk stays scoped to the study companies.
    """
    cur = conn.cursor()

    funda_gvkeys = {row[0] for row in
                    cur.execute("SELECT DISTINCT gvkey FROM compustat_funda")}

    # Indexes from the Compustat side for the fallbacks.
    tic_to_gvkeys, cusip_to_gvkeys = {}, {}
    for gvkey, tic, cusip in cur.execute(
            "SELECT DISTINCT gvkey, tic, cusip FROM compustat_funda"):
        t = _clean(tic)
        if t:
            tic_to_gvkeys.setdefault(t, set()).add(gvkey)
        c = _cusip8(cusip)
        if c:
            cusip_to_gvkeys.setdefault(c, set()).add(gvkey)

    mapping = cur.execute(
        "SELECT rcid, gvkey, ticker, cusip FROM revelio_company_mapping"
    ).fetchall()

    # (gvkey, rcid) -> (method, confidence); dict de-dupes repeated links.
    links = {}
    for rcid, gvkey, ticker, cusip in mapping:
        if not rcid:
            continue
        gk = _clean(gvkey)
        if gk and gk in funda_gvkeys:
            links[(gk, rcid)] = ("revelio_gvkey", 0.99)
            continue
        # Fallbacks only when Revelio gives no usable gvkey.
        t = _clean(ticker)
        if t and t in tic_to_gvkeys:
            for cand in tic_to_gvkeys[t]:
                links.setdefault((cand, rcid), ("ticker", 0.90))
            continue
        c = _cusip8(cusip)
        if c and c in cusip_to_gvkeys:
            for cand in cusip_to_gvkeys[c]:
                links.setdefault((cand, rcid), ("cusip", 0.92))

    rows = [(gvkey, rcid, method, conf)
            for (gvkey, rcid), (method, conf) in sorted(links.items())]

    cur.execute("DELETE FROM company_crosswalk;")
    cur.executemany(
        "INSERT INTO company_crosswalk (gvkey, rcid, match_method, match_confidence) "
        "VALUES (?, ?, ?, ?);",
        rows,
    )
    conn.commit()
    return rows

# ===== matching.py =====
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
    """Aggregate Execucomp to one record per (execid, gvkey) within the 

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
    return any(kw in low for kw in EXEC_ROLE_KEYWORDS)


def _tier(name, seniority_ok, date_overlap):
    corroborated = seniority_ok or date_overlap
    if name >= NAME_STRONG and corroborated:
        return "high"
    if name >= NAME_STRONG or (name >= NAME_WEAK and corroborated):
        return "medium"
    if name >= NAME_WEAK:
        return "low"
    return None


def match_executives(conn, min_tier=DEFAULT_MIN_TIER):
    """Score Execucomp<->Revelio candidates and load ``exec_revelio_link``.

    Returns a summary dict (candidate count, accepted count, distinct execs
    matched). Every candidate scoring at least a weak name match is recorded;
    ``accepted`` reflects ``min_tier`` and ``is_best`` flags the top accepted
    Revelio person per (execid, gvkey).
    """
    cur = conn.cursor()
    min_rank = TIER_ORDER.index(min_tier)

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
            if nscore < NAME_WEAK:
                continue

            seniority_ok = any((p["seniority"] or 0) >= EXEC_SENIORITY_MIN
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
                nscore * W_NAME
                + (1.0 if (seniority_ok or role_ok) else 0.0) * W_SENIORITY
                + (1.0 if date_overlap else 0.0) * W_DATE,
                4,
            )
            accepted = TIER_ORDER.index(tier) >= min_rank

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
        exec_lvl = (p["seniority"] or 0) >= EXEC_SENIORITY_MIN or _role_is_exec(p["role_raw"])
        overlap = p["has_dates"] and _overlaps(p["win"], exec_window)
        return (exec_lvl and overlap, overlap, exec_lvl, p["seniority"] or 0)

    return max(positions, key=rank)


def _display_name(name):
    parts = [p for p in (name.get("first"), name.get("last")) if p]
    return " ".join(parts).title() if parts else None

# ===== workhistory.py =====
"""Assemble each matched executive's complete Revelio work history.

For every accepted best match (``exec_revelio_link.is_best = 1``) we take the
Revelio ``user_id`` and pull *all* of that person's position spells -- the full
career trajectory across every company, not just the focal firm -- attaching the
Compustat ``gvkey`` of each company where Revelio's mapping provides one. This is
the primary deliverable: the executives' complete work history plus Revelio's
modeled salary for each spell.
"""



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
                normalize(job_category), seniority, salary,
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

# ===== mobility.py =====
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



def _max_observed_year(cur):
    years = []
    for (startdate, enddate) in cur.execute(
            "SELECT startdate, enddate FROM revelio_positions"):
        for d in (startdate, enddate):
            if d and d.strip()[:4].isdigit():
                years.append(int(d.strip()[:4]))
    return max(years) if years else MAX_FYEAR


def build_mobility(conn):
    """Populate ``exec_mobility``; return the number of rows written."""
    cur = conn.cursor()
    ref_year = _max_observed_year(cur)
    thresh = EXEC_SENIORITY_MIN

    # Focal rcids per executive (where Execucomp observed them).
    focal = defaultdict(set)
    for execid, rcid in cur.execute(
            "SELECT execid, rcid FROM exec_revelio_link "
            "WHERE is_best = 1 AND accepted = 1 AND rcid IS NOT NULL"):
        focal[execid].add(rcid)

    # All spells per matched (execid, user_id), already sorted chronologically.
    spells = defaultdict(list)
    for (execid, user_id, position_number, rcid, seniority, job_category,
         startdate, enddate) in cur.execute(
            "SELECT execid, user_id, position_number, rcid, seniority, "
            "job_category, startdate, enddate FROM exec_work_history "
            "ORDER BY execid, user_id, position_number"):
        spells[(execid, user_id)].append({
            "pos": position_number if position_number is not None else 0,
            "rcid": rcid, "seniority": seniority or 0,
            "job_category": job_category,
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
            primary((p["job_category"], p["seniority"]) for p in ps),
            start_year, end_year,
            (end_year - start_year) if (start_year is not None and end_year is not None) else None,
            n_prior, internal, external,
        ))

    cur.execute("DELETE FROM exec_mobility;")
    cur.executemany(
        """
        INSERT INTO exec_mobility
        (execid, user_id, n_positions, n_employers, max_seniority,
         n_exec_positions, primary_job_category, career_start_year,
         career_end_year, experience_years,
         n_prior_employers_before_focal, internal_promotion, external_hire)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

# ===== panels.py =====
"""Build the two analytical panels: executive-year and firm-year.

``executive_year_panel`` (execid x gvkey x year) is built first, in Python, so
we can attach -- for each matched executive and year -- the Revelio position
that was *active that year* (its seniority, role and modeled salary).
``firm_year_panel`` (gvkey x year) is then aggregated with SQL from the universe,
Compustat fundamentals, Execucomp NEOs and the executive-year panel.
"""

from collections import defaultdict



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
                rev_jobcat = normalize(pos["job_category"])
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

# ===== report.py =====
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

# ===== export.py =====
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

# ===== build_database.py =====
"""Build the Execucomp + Compustat + Revelio executive panel (SQLite).

Usage::

    python -m execucomp_revelio \
        --funda     path/to/compustat_funda.csv \
        --index     path/to/idxcst_his.csv \
        --execucomp path/to/execucomp_anncomp.csv \
        --individual        path/to/revelio_individual.csv \
        --positions         path/to/revelio_positions.csv \
        --company-mapping   path/to/revelio_company_mapping.csv \
        --output    execucomp_revelio.db \
        [--min-tier {high,medium,low}] [--index-gvkeyx 000400 000600]

With no source arguments the bundled sample data is used, so the pipeline runs
end-to-end out of the box::

    python -m execucomp_revelio

Pipeline stages (each idempotent; tables are dropped and rebuilt every run):

    1. load raw sources
    2. universe_firm_year   (S&P 1000, FY window, ex financials & utilities)
    3. company_crosswalk    (gvkey <-> rcid, from Revelio's gvkey)
    4. exec_revelio_link    (Execucomp exec <-> Revelio person, scored & tiered)
    5. exec_work_history    (complete Revelio career of matched executives)
    6. firm_year_panel + executive_year_panel  (the deliverables)
"""

import argparse
import logging
import os
import sqlite3


LOG = logging.getLogger("execucomp_revelio")

_HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.path.join(_HERE, "sample_data")
DEFAULTS = {
    "funda": os.path.join(SAMPLE_DIR, "compustat_funda_sample.csv"),
    "index": os.path.join(SAMPLE_DIR, "compustat_idxcst_his_sample.csv"),
    "execucomp": os.path.join(SAMPLE_DIR, "execucomp_anncomp_sample.csv"),
    "individual": os.path.join(SAMPLE_DIR, "revelio_individual_sample.csv"),
    "positions": os.path.join(SAMPLE_DIR, "revelio_positions_sample.csv"),
    "company_mapping": os.path.join(SAMPLE_DIR, "revelio_company_mapping_sample.csv"),
}
DEFAULT_OUTPUT = os.path.join(_HERE, "execucomp_revelio.db")


def create_schema(conn):
    cur = conn.cursor()
    for table in ALL_TABLES:
        cur.execute(f"DROP TABLE IF EXISTS {table};")
    for statement in CREATE_STATEMENTS:
        cur.execute(statement)
    for index in INDEXES:
        cur.execute(index)
    conn.commit()


_INSERTS = {
    "compustat_funda":
        "INSERT INTO compustat_funda (gvkey, fyear, datadate, tic, cusip, cik, "
        "conm, sale, at, ni, ceq, dltt, capx, xrd, emp, naics, sic, sich) "
        "VALUES (" + ",".join("?" * 18) + ");",
    "compustat_index_constituents":
        "INSERT INTO compustat_index_constituents (gvkey, gvkeyx, conm, "
        "indexname, from_date, thru_date) VALUES (" + ",".join("?" * 6) + ");",
    "execucomp_anncomp":
        "INSERT INTO execucomp_anncomp (gvkey, year, execid, co_per_rol, "
        "exec_fullname, exec_fname, exec_mname, exec_lname, coname, title, "
        "ceoann, cfoann, joined_co, leftco, salary, bonus, tdc1, tdc2, age, "
        "gender) VALUES (" + ",".join("?" * 20) + ");",
    "revelio_individual":
        "INSERT INTO revelio_individual (user_id, fullname, firstname, "
        "lastname, gender, ethnicity) VALUES (" + ",".join("?" * 6) + ");",
    "revelio_positions":
        "INSERT INTO revelio_positions (position_id, user_id, rcid, company, "
        "position_number, role_raw, role_k150, role_k1500, job_category, "
        "seniority, salary, startdate, enddate, location) "
        "VALUES (" + ",".join("?" * 14) + ");",
    "revelio_company_mapping":
        "INSERT INTO revelio_company_mapping (rcid, company, ticker, cusip, "
        "isin, gvkey, lei, naics, sic) VALUES (" + ",".join("?" * 9) + ");",
    "constituents_list":
        "INSERT INTO constituents_list (ticker, company, cik, gvkey, "
        "index_name, from_year, thru_year) VALUES (" + ",".join("?" * 7) + ");",
}


def load_sources(conn, paths):
    cur = conn.cursor()
    loaded = {}
    for table, loader, path in [
        ("compustat_funda", load_compustat_funda, paths["funda"]),
        ("compustat_index_constituents", load_index_constituents, paths["index"]),
        ("execucomp_anncomp", load_execucomp, paths["execucomp"]),
        ("revelio_individual", load_revelio_individual, paths["individual"]),
        ("revelio_positions", load_revelio_positions, paths["positions"]),
        ("revelio_company_mapping", load_revelio_company_mapping, paths["company_mapping"]),
    ]:
        rows = loader(path)
        cur.executemany(_INSERTS[table], rows)
        loaded[table] = len(rows)
    conn.commit()
    return loaded


def build_database(paths, output_path, min_tier=DEFAULT_MIN_TIER,
                   index_gvkeyx=SP1000_INDEX_GVKEYX,
                   min_fyear=MIN_FYEAR, max_fyear=MAX_FYEAR,
                   excluded_sic_ranges=EXCLUDED_SIC_RANGES,
                   export_dir=None, constituents_path=None):
    """Run the full pipeline; return a summary dict of stage counts.

    The universe is built from ``compustat_index_constituents`` (idxcst_his) by
    default, or -- if ``constituents_path`` is given -- from an explicit
    constituent list resolved to gvkey via CIK/ticker (the ``--constituents``
    path). If ``export_dir`` is given, the deliverable tables are also written
    out as CSV files there (in addition to the SQLite database).
    """
    if os.path.exists(output_path):
        os.remove(output_path)

    conn = sqlite3.connect(output_path)
    exported = None
    universe_stats = None
    try:
        create_schema(conn)
        loaded = load_sources(conn, paths)
        LOG.info("Loaded sources: %s", loaded)

        if constituents_path:
            crows = load_constituents(constituents_path)
            conn.executemany(_INSERTS["constituents_list"], crows)
            conn.commit()
            uni, universe_stats = build_universe_from_list(
                conn, min_fyear, max_fyear, excluded_sic_ranges)
            LOG.info("Universe from list: %d firm-years (FY %d-%d, ex SIC); "
                     "resolution %s", len(uni), min_fyear, max_fyear, universe_stats)
        else:
            uni = build_universe(
                conn, index_gvkeyx, min_fyear, max_fyear, excluded_sic_ranges)
            LOG.info("Universe: %d firm-years (S&P 1000, FY %d-%d, ex SIC)",
                     len(uni), min_fyear, max_fyear)

        links = build_crosswalk(conn)
        LOG.info("Company crosswalk: %d gvkey<->rcid links", len(links))

        match_summary = match_executives(conn, min_tier=min_tier)
        LOG.info("Exec matching (min_tier=%s): %d candidates, %d accepted, "
                 "%d execs matched", min_tier, match_summary["candidates"],
                 match_summary["accepted"], match_summary["execs_matched"])

        n_wh_execs, n_wh_rows = build_work_history(conn)
        LOG.info("Work history: %d positions for %d matched execs",
                 n_wh_rows, n_wh_execs)

        n_mobility = build_mobility(conn)
        LOG.info("Mobility features: %d matched executives", n_mobility)

        n_exec_year, n_firm_year = build_panels(conn)
        LOG.info("Panels: %d executive-years, %d firm-years",
                 n_exec_year, n_firm_year)

        quality = build_report(conn)
        LOG.info("Match rate: %s (%d/%d NEOs)", quality["match_rate"],
                 quality["matched_execs"], quality["total_execs"])

        if export_dir:
            exported = export_tables(conn, export_dir)
            os.makedirs(export_dir, exist_ok=True)
            with open(os.path.join(export_dir, "match_quality_report.txt"),
                      "w", encoding="utf-8") as fh:
                fh.write(format_report(quality) + "\n")
            LOG.info("Exported %d CSV files + report to %s",
                     len(exported), export_dir)
    finally:
        conn.close()

    return {
        "loaded": loaded,
        "universe_rows": len(uni),
        "universe_stats": universe_stats,
        "crosswalk_links": len(links),
        "match": match_summary,
        "work_history_execs": n_wh_execs,
        "work_history_rows": n_wh_rows,
        "mobility_rows": n_mobility,
        "executive_year_rows": n_exec_year,
        "firm_year_rows": n_firm_year,
        "report": quality,
        "output": output_path,
        "exported": exported,
    }


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Build the Execucomp + Compustat + Revelio executive panel.")
    p.add_argument("--funda", default=DEFAULTS["funda"],
                   help="Compustat funda CSV (default: bundled sample).")
    p.add_argument("--index", default=DEFAULTS["index"],
                   help="Compustat idxcst_his CSV (default: bundled sample).")
    p.add_argument("--execucomp", default=DEFAULTS["execucomp"],
                   help="Execucomp anncomp CSV (default: bundled sample).")
    p.add_argument("--individual", default=DEFAULTS["individual"],
                   help="Revelio individual CSV (default: bundled sample).")
    p.add_argument("--positions", default=DEFAULTS["positions"],
                   help="Revelio positions CSV (default: bundled sample).")
    p.add_argument("--company-mapping", default=DEFAULTS["company_mapping"],
                   dest="company_mapping",
                   help="Revelio company mapping CSV (default: bundled sample).")
    p.add_argument("--output", default=DEFAULT_OUTPUT,
                   help="Path for the output SQLite database.")
    p.add_argument("--min-tier", default=DEFAULT_MIN_TIER,
                   choices=TIER_ORDER,
                   help="Lowest match tier to accept (high=strict, "
                        "medium=balanced [default], low=lenient).")
    p.add_argument("--index-gvkeyx", nargs="+", default=list(SP1000_INDEX_GVKEYX),
                   help="Compustat gvkeyx codes that define the S&P 1000 "
                        "(MidCap 400 + SmallCap 600).")
    p.add_argument("--min-fyear", type=int, default=MIN_FYEAR)
    p.add_argument("--max-fyear", type=int, default=MAX_FYEAR)
    p.add_argument("--export-dir", default=None,
                   help="If set, also write the panels, work history and match "
                        "table as CSV files into this directory.")
    p.add_argument("--constituents", default=None,
                   help="Optional constituent-list CSV (columns: ticker/cik/"
                        "gvkey [+ company, index_name, from_year, thru_year]). "
                        "If given, the universe is built from this list "
                        "(resolved to gvkey) instead of from idxcst_his.")
    return p.parse_args(argv)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args(argv)
    paths = {
        "funda": args.funda, "index": args.index, "execucomp": args.execucomp,
        "individual": args.individual, "positions": args.positions,
        "company_mapping": args.company_mapping,
    }
    s = build_database(
        paths, args.output, min_tier=args.min_tier,
        index_gvkeyx=tuple(args.index_gvkeyx),
        min_fyear=args.min_fyear, max_fyear=args.max_fyear,
        export_dir=args.export_dir, constituents_path=args.constituents,
    )
    print(
        "Built {output}\n"
        "  Sources loaded        : {loaded}\n"
        "  Universe firm-years   : {universe_rows}\n"
        "  Company links         : {crosswalk_links}\n"
        "  Exec match candidates : {match[candidates]} "
        "({match[accepted]} accepted, {match[execs_matched]} execs)\n"
        "  Work-history rows     : {work_history_rows} "
        "for {work_history_execs} execs\n"
        "  Mobility features     : {mobility_rows} execs\n"
        "  Executive-year panel  : {executive_year_rows} rows\n"
        "  Firm-year panel       : {firm_year_rows} rows"
        .format(**s)
    )
    print()
    print(format_report(s["report"]))
    if s["exported"]:
        print("  CSV exports:")
        for table, (path, count) in s["exported"].items():
            print(f"    {path} ({count} rows)")



if __name__ == "__main__":
    import sys
    if len(sys.argv) == 1:
        sys.argv += ["--funda", "wrds_csv/compustat_funda.csv",
                     "--index", "wrds_csv/compustat_idxcst_his.csv",
                     "--execucomp", "wrds_csv/execucomp_anncomp.csv",
                     "--individual", "wrds_csv/revelio_individual.csv",
                     "--positions", "wrds_csv/revelio_positions.csv",
                     "--company-mapping", "wrds_csv/revelio_company_mapping.csv",
                     "--output", "execucomp_revelio.db", "--export-dir", "out"]
    main()

