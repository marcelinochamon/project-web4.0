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

# Inclusive SIC code ranges to drop from the universe. Default per the user's
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
