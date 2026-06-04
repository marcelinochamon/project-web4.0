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
