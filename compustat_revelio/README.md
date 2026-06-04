# Compustat + Revelio Combined Database

A self-contained pipeline that ingests **Compustat** financial fundamentals and
**Revelio Labs** workforce data, links the two providers on company
identifiers, and merges them into a single firm-year SQLite database.

This module is independent of the restaurant waitlist Django app that lives in
`new_rest/`. It has **no third-party dependencies** — only the Python standard
library (`sqlite3`, `csv`).

## Quick start

Build the database from the bundled sample data:

```bash
python -m compustat_revelio
```

This writes `compustat_revelio/compustat_revelio.db` and prints a summary:

```
Built .../compustat_revelio/compustat_revelio.db
  Compustat firm-years : 15
  Revelio firm-years   : 16
  Company links        : 5
  Merged panel rows    : 15 (15 with workforce data)
```

Build from your own data:

```bash
python -m compustat_revelio \
    --compustat path/to/compustat.csv \
    --revelio   path/to/revelio.csv \
    --crosswalk path/to/manual_links.csv \   # optional
    --output    path/to/output.db
```

## Input formats

### Compustat fundamentals (`--compustat`)

One row per firm-year. Header columns:

| column | type | meaning |
| ------ | ---- | ------- |
| `gvkey` | text | Compustat permanent company id |
| `fyear` | int | fiscal year |
| `datadate` | text | fiscal period end date (`YYYY-MM-DD`) |
| `tic` | text | exchange ticker |
| `cusip` | text | 9-character CUSIP |
| `conm` | text | company name |
| `sale` | float | revenue, USD millions |
| `at` | float | total assets, USD millions |
| `ni` | float | net income, USD millions |
| `emp` | float | employees, **thousands** (as reported) |
| `naics` | text | NAICS industry code |
| `sic` | text | SIC industry code |

### Revelio workforce (`--revelio`)

One row per firm-year. Header columns:

| column | type | meaning |
| ------ | ---- | ------- |
| `rcid` | text | Revelio company id |
| `company` | text | company name |
| `year` | int | calendar year |
| `headcount` | int | estimated total headcount |
| `hires` | int | estimated hires during the year |
| `departures` | int | estimated departures during the year |
| `attrition_rate` | float | departures / headcount |
| `avg_tenure` | float | average tenure, years |
| `avg_salary` | float | estimated average salary, USD |
| `ticker` | text | mapped exchange ticker |

### Manual crosswalk (`--crosswalk`, optional)

Overrides/augments the automatic link. Only `gvkey` and `rcid` are required;
extra columns (e.g. `note`) are ignored.

```csv
gvkey,rcid,note
184996,5005,Tesla has no ticker in the Revelio feed; link it manually
```

## How the link works

The two providers are joined at the **company** level into `company_crosswalk`
(`gvkey` ↔ `rcid`), then at the **firm-year** level into the merged panel:

1. **Ticker match** — Compustat `tic` == Revelio `ticker` → confidence `0.95`
   (a ticker shared by multiple Revelio companies is kept but flagged
   `ticker_ambiguous`, confidence `0.40`).
2. **Manual overrides** from the crosswalk CSV → confidence `1.00`. These take
   precedence over heuristic matches.

The merged `firm_year_panel` is built with a `LEFT JOIN` from Compustat, so
**every Compustat firm-year is preserved** even when no Revelio match exists —
coverage gaps are explicit (`rcid IS NULL`) rather than silently dropped.

## Output schema

| table | grain | description |
| ----- | ----- | ----------- |
| `compustat_fundamentals` | gvkey × fyear | raw Compustat, as loaded |
| `revelio_workforce` | rcid × year | raw Revelio, as loaded |
| `company_crosswalk` | gvkey × rcid | the company link + provenance |
| `firm_year_panel` | gvkey × year | **the combined database** |

`firm_year_panel` carries the source fields plus derived cross-source metrics:

- `revenue_per_employee_usd` — Compustat `sale` (USD) / Revelio `headcount`
- `compustat_emp_count` — reported `emp` × 1000 (headcount basis)
- `headcount_coverage` — Revelio `headcount` / reported employees
- `net_hiring` — `hires` − `departures`
- `match_method`, `match_confidence` — how the firm was linked

## Rebuilding

The build is **idempotent**: tables are dropped and rebuilt on every run, and
the raw source tables are retained so the crosswalk and panel can be rebuilt or
audited without re-ingesting the providers.

## Tests

```bash
python -m unittest discover -s compustat_revelio
```

## Module layout

```
compustat_revelio/
├── __main__.py          # `python -m compustat_revelio` entry point
├── build_database.py    # orchestration + CLI
├── schema.py            # SQL DDL for all tables
├── loaders.py           # CSV readers with type coercion
├── linking.py           # gvkey <-> rcid crosswalk builder
├── sample_data/         # runnable example inputs
└── tests/               # unittest suite
```
