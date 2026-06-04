"""Execucomp + Compustat + Revelio executive panel pipeline.

A self-contained, standard-library-only pipeline that builds a research panel
linking three providers around a common ``gvkey`` spine:

* **Compustat** annual fundamentals (``funda``) and S&P index history
  (``idxcst_his``) -> the firm-year universe (S&P 1000, FY 2009-2019, ex
  financials & utilities).
* **Execucomp** annual compensation (``anncomp``) -> the named executive
  officers (NEOs) of each firm-year.
* **Revelio Labs** individual data (user / positions / company mapping) -> each
  executive's *complete work history* and Revelio's *modeled annual salary*.

The Revelio company-mapping file carries ``gvkey`` directly, so companies link
to Compustat/Execucomp on ``gvkey`` (no fuzzy company matching). Executives are
matched to Revelio individuals with a scored, tiered matcher (name + company +
seniority/role + tenure-date overlap), with a tunable acceptance threshold.

This module is independent of the restaurant waitlist Django app in this repo
and of the firm-level ``compustat_revelio`` module; it has no third-party
dependencies.
"""

from .build_database import build_database

__all__ = ["build_database"]
