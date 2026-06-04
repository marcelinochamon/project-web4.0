"""Combined Compustat + Revelio database pipeline.

A self-contained, standard-library-only pipeline that ingests Compustat
financial fundamentals and Revelio workforce data, links the two providers on
company identifiers, and merges them into a single firm-year SQLite database.

This module is independent of the restaurant waitlist Django app in this repo.
"""

from .build_database import build_database

__all__ = ["build_database"]
