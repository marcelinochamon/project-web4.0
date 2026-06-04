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
