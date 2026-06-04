# Execucomp + Compustat + Revelio Executive Panel

A self-contained pipeline that builds a research panel linking **three WRDS
providers** around a common `gvkey` spine, to recover the **complete work
history (and Revelio modeled salary) of every Execucomp executive** in the
**S&P 1000**, FY **2009–2019**, excluding financials and utilities.

* **Compustat** — annual fundamentals (`funda`) + S&P index history
  (`idxcst_his`) → the firm-year universe.
* **Execucomp** — annual compensation (`anncomp`) → the named executive
  officers (NEOs) of each firm-year.
* **Revelio Labs** — individual *user*, *positions*, and *company-mapping*
  files → each executive’s full career trajectory and modeled annual salary.

No third-party dependencies — only the Python standard library (`sqlite3`,
`csv`). Independent of the `compustat_revelio` (firm-level) module and the
`new_rest/` Django app.

## Quick start

```bash
python -m execucomp_revelio                 # builds from bundled sample data
```

```
Universe firm-years   : 4
Company links         : 3
Exec match candidates : 4 (4 accepted, 4 execs)
Work-history rows     : 9 for 4 execs
Executive-year panel  : 10 rows
Firm-year panel       : 4 rows
```

Build from your own WRDS extracts:

```bash
python -m execucomp_revelio \
    --funda            path/to/compustat_funda.csv \
    --index            path/to/idxcst_his.csv \
    --execucomp        path/to/execucomp_anncomp.csv \
    --individual       path/to/revelio_individual.csv \
    --positions        path/to/revelio_positions.csv \
    --company-mapping  path/to/revelio_company_mapping.csv \
    --output           execucomp_revelio.db \
    --min-tier medium \
    --index-gvkeyx 000400 000600 \
    --export-dir       ./out          # optional: also write CSVs
```

## CSV export

The pipeline always writes the SQLite database. Pass `--export-dir DIR` to
*also* drop flat CSV files (openable in Excel / Stata / R / pandas) for the
deliverable tables:

```
out/firm_year_panel.csv
out/executive_year_panel.csv
out/exec_work_history.csv
out/exec_revelio_link.csv      # the scored match / review table
```

`NULL` values render as empty cells. This uses the standard-library `csv`
module — no extra dependency. (Parquet is intentionally not included, as it
would require `pyarrow`; ask if you want it.)

## How the link works (and why)

| Link | Key | Method |
| ---- | --- | ------ |
| Compustat ↔ Execucomp | `gvkey` | direct (both keyed on gvkey) |
| Compustat ↔ Revelio **company** | `gvkey` | **direct** — Revelio’s company-mapping file carries `gvkey`; ticker/CUSIP are fallbacks only |
| Execucomp exec ↔ Revelio **person** | name + company + seniority/role + dates | scored & tiered matcher |

Revelio publishes a `gvkey` on its company mapping, so companies join straight
to Compustat — no fuzzy company matching. Only the **executive ↔ person** link
is probabilistic.

### Executive matcher

For each Execucomp executive at a `gvkey`, candidates are restricted to Revelio
people who held a position at one of that company’s `rcid` entities, then scored:

```
total_score = name·0.60 + seniority_ok·0.20 + date_overlap·0.20
```

* **name** — normalized full-name similarity (0–1, accents/suffixes stripped).
* **seniority_ok** — the person held an executive-level Revelio position
  (`seniority ≥ 6`) or a role whose text matches an executive keyword.
* **date_overlap** — a Revelio position spell overlaps the executive’s
  Execucomp service window (`joined_co`…`leftco`).
* **salary_ratio** — Revelio modeled salary ÷ Execucomp base salary, recorded
  as a **sanity check only** (modeled ≠ reported cash), never used to gate.

Each candidate gets a **tier**:

| tier | condition |
| ---- | --------- |
| `high` | strong name + same company + (executive seniority **or** date overlap) |
| `medium` | strong name + same company, **or** weak name + corroborating signal |
| `low` | weak name + same company only |

`--min-tier` sets the acceptance floor — `high` (strict), `medium` (balanced,
default), `low` (lenient). **Every** candidate is written to
`exec_revelio_link` with its scores and an `accepted` flag, so you can inspect
results and slide the threshold without rerunning the match logic. `is_best`
flags the top accepted person per (execid, gvkey).

## Input formats

Extra columns are ignored; a missing expected column raises a clear error.
Dates are `YYYY-MM-DD` (only the year is used for windows). See
`sample_data/` for runnable examples of every file.

| file (flag) | grain | key columns |
| ----------- | ----- | ----------- |
| `--funda` | gvkey × fyear | `gvkey, fyear, datadate, tic, cusip, conm, sale, at, ni, ceq, dltt, capx, xrd, emp, naics, sic, sich` |
| `--index` | membership spell | `gvkey, gvkeyx, conm, indexname, from_date, thru_date` |
| `--execucomp` | exec × year | `gvkey, year, execid, exec_fullname, exec_fname, exec_mname, exec_lname, coname, title, ceoann, cfoann, joined_co, leftco, salary, bonus, tdc1, tdc2, age, gender` |
| `--individual` | user | `user_id, fullname, firstname, lastname, gender, ethnicity` |
| `--positions` | position | `position_id, user_id, rcid, company, position_number, role_raw, role_k150, role_k1500, seniority, salary, startdate, enddate, location` |
| `--company-mapping` | rcid | `rcid, company, ticker, cusip, isin, gvkey, lei, naics, sic` |

> **Revelio column names.** These follow Revelio’s WRDS individual datasets
> (user / positions / company-reference) and modeled-salary field. Confirm the
> exact names in your WRDS vintage and adjust `loaders.py` if they differ; the
> coercion specs there are the single source of truth for expected headers.

## Output tables

| table | grain | description |
| ----- | ----- | ----------- |
| `compustat_funda`, `compustat_index_constituents`, `execucomp_anncomp`, `revelio_individual`, `revelio_positions`, `revelio_company_mapping` | — | raw sources, as loaded |
| `universe_firm_year` | gvkey × year | S&P 1000, in window, ex-SIC spine |
| `company_crosswalk` | gvkey × rcid | company link + provenance |
| `exec_revelio_link` | execid × gvkey × user | **scored, tiered candidate matches** |
| `exec_work_history` | execid × user × position | **each matched exec’s complete Revelio career + modeled salary** |
| `firm_year_panel` | gvkey × year | **deliverable** — financials + NEO comp aggregates + matched-exec Revelio salary |
| `executive_year_panel` | execid × gvkey × year | **deliverable** — per-exec comp + the Revelio position active that year |

`exec_work_history` is the primary deliverable: for every matched executive it
contains *all* their Revelio position spells across *every* employer (prior,
non-universe firms carry a `NULL` gvkey), with seniority, role and modeled
annual salary.

## Configuration

Defaults live in `config.py` (all overridable):

* `MIN_FYEAR` / `MAX_FYEAR` — study window (2009–2019).
* `SP1000_INDEX_GVKEYX` — Compustat `gvkeyx` codes for S&P MidCap 400 +
  SmallCap 600. **Verify these against your WRDS environment** —
  `SELECT DISTINCT gvkeyx, conm FROM comp.idxcst_his` — and override via
  `--index-gvkeyx`. The bundled placeholders (`000400`, `000600`) match the
  sample data.
* `EXCLUDED_SIC_RANGES` — financials `6000–6999` and utilities `4900–4949`
  (historical `sich` preferred over header `sic`).
* `EXEC_SENIORITY_MIN`, `EXEC_ROLE_KEYWORDS`, `NAME_STRONG`/`NAME_WEAK`, the
  score weights, and `DEFAULT_MIN_TIER` — matcher tunables.

## Rebuilding

Idempotent: every run drops and rebuilds all tables, and the raw source tables
are retained so the universe, crosswalk, match and panels can be rebuilt or
audited without re-ingesting the providers.

## Tests

```bash
python -m unittest discover -s execucomp_revelio
```

## Module layout

```
execucomp_revelio/
├── __main__.py          # `python -m execucomp_revelio`
├── build_database.py    # orchestration + CLI
├── config.py            # window, S&P codes, SIC exclusions, matcher tunables
├── schema.py            # SQL DDL for all tables
├── loaders.py           # CSV readers with type coercion (expected headers)
├── names.py             # name normalization + similarity score
├── universe.py          # S&P 1000 / window / SIC filter
├── crosswalk.py         # gvkey <-> rcid (Revelio gvkey + ticker/cusip fallback)
├── matching.py          # executive <-> Revelio person matcher (scored/tiered)
├── workhistory.py       # complete work history of matched executives
├── panels.py            # firm-year + executive-year panels
├── export.py            # optional CSV export of the deliverable tables
├── sample_data/         # runnable example inputs (6 CSVs)
└── tests/               # unittest suite
```
