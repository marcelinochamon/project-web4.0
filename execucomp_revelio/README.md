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
    --index-gvkeyx 024248 030824 \
    --export-dir       ./out          # optional: also write CSVs
```

## Getting the data from WRDS

The six inputs come from WRDS, which requires *your* authenticated account
(username + Duo 2FA) and direct network access — so extraction runs on your
side, not in a sandbox. `wrds_extract.py` automates it with the official `wrds`
package, writing CSVs whose headers match this pipeline exactly:

```bash
pip install wrds pandas
# 1) confirm the library/table/column names + index codes in your WRDS vintage
python -m execucomp_revelio.wrds_extract --username YOUR_WRDS_ID --list
# 2) extract the six inputs (S&P 1000, FY 2009-2019) to ./wrds_csv
python -m execucomp_revelio.wrds_extract --username YOUR_WRDS_ID --outdir ./wrds_csv
# 3) build the databases
python -m execucomp_revelio \
    --funda ./wrds_csv/compustat_funda.csv --index ./wrds_csv/compustat_idxcst_his.csv \
    --execucomp ./wrds_csv/execucomp_anncomp.csv \
    --individual ./wrds_csv/revelio_individual.csv \
    --positions ./wrds_csv/revelio_positions.csv \
    --company-mapping ./wrds_csv/revelio_company_mapping.csv \
    --export-dir ./out
```

It scopes Compustat/Execucomp to the S&P 1000 gvkeys and the window, and pulls
Revelio in two stages: **(1) seed** the candidate executives at the focal firms,
then **(2)** pull *every* position for those people — **with no seniority
filter**, so each executive's junior/early-career roles are included (the full
work history). Seeding (`--seed`) defaults to **`name`** (Execucomp name-match
at *any* seniority, so no executive is lost to a Revelio seniority mislabel);
`seniority` (senior roles only) and `all` (every employee) are alternatives. The SQL is
plain `db.raw_sql`, so you can also paste the queries into the WRDS web query
tool. Run `--list` first and adjust the `TABLES` config at the top of the
script if your schema names differ (Execucomp/Revelio table names drift).

> Don't commit the resulting WRDS/Revelio CSVs — they're licensed data. Keep
> them local and run the pipeline there (it has no third-party deps).

## Defining the universe (two modes)

**Default — `idxcst_his` (recommended).** Pass the historical constituent table
via `--index`; membership is derived per firm-year from the from/thru dates.
This is historically accurate for 2009–2019 and already keyed by `gvkey`.

**Alternative — explicit constituent list (`--constituents`).** Supply a CSV
keyed on `ticker`, `cik`, and/or `gvkey`; the pipeline resolves each to a
`gvkey` against Compustat `funda` (preferring `gvkey` → `cik` → `ticker`) and
prints a resolution summary (`by_gvkey/by_cik/by_ticker/unresolved/ambiguous`).
Optional `from_year`/`thru_year` columns scope membership by year.

```bash
python -m execucomp_revelio --constituents sp1000_constituents.csv --export-dir ./out
```

> ⚠️ **Survivorship bias.** A *current* constituent list (e.g. Wikipedia’s
> "List of S&P 400/600 companies") omits firms that left the index before today
> and includes recent additions, so applying it across 2009–2019 biases the
> sample. Use it for prototyping; use `idxcst_his` for the final panel.

### Wikipedia → constituent CSV

`wiki_parse` turns saved Wikipedia pages (Safari `.webarchive`, saved `.html`,
or a plain-text paste) of "List of S&P 400/600 companies" into clean CSVs, with
no transcription error:

```bash
# current constituents (ticker,company,cik,index_name)
python -m execucomp_revelio.wiki_parse sp400.webarchive sp600.webarchive \
    -o sp1000_constituents.csv

# the index change log (date,year,action,ticker,company,index_name,reason)
python -m execucomp_revelio.wiki_parse --kind changes \
    sp400.webarchive sp600.webarchive -o sp1000_changes.csv
```

It handles both the S&P 400 (ticker + name) and S&P 600 (ticker + name + CIK)
formats and de-duplicates repeated uploads.

A snapshot is bundled in `data/`:

| file | rows | notes |
| ---- | ---- | ----- |
| `data/sp1000_constituents_current.csv` | 1,003 | 400 MidCap + 603 SmallCap (all 603 with CIK) — **current** membership |
| `data/sp1000_index_changes.csv` | ~2,104 | add/remove events, **2012→2026** |
| `data/sp1000_reconstructed_2009_2019.csv` | ~1,312 | backward-reconstructed membership spans (see below) |

### Reconstructing historical membership

`reconstruct` walks the change log backward from the *current* list to recover
who was a member at each past year-end (a company "added" on date D was not a
member before D; one "removed" on D was), emitting `from_year`/`thru_year`
spans for `--constituents`:

```bash
python -m execucomp_revelio.reconstruct sp400.webarchive sp600.webarchive \
    --min-year 2009 --max-year 2019 -o sp1000_reconstructed.csv
```

It prints a coverage report and only emits years at/after each index's oldest
logged change (its "floor year"). For these captures that means:

| index | reconstructable | **not** covered in 2009–2019 |
| ----- | --------------- | ---------------------------- |
| S&P 400 MidCap | 2012–2019 | 2009, 2010, 2011 |
| S&P 600 SmallCap | 2019 only | 2009–2018 |

> The reconstructed MidCap counts run slightly above 400/year (share-class
> duplicates + one-sided index changes accumulating over the walk). Treat this
> as a **best-effort proxy**, not ground truth — for the full, exact 2009–2019
> universe use WRDS `idxcst_his`.

> ⚠️ **The change log does not cover the early study years.** The S&P 400 log
> starts ~2012 and the S&P 600 log ~2019, so it cannot reconstruct 2009–2011
> (400) or 2009–2018 (600) membership. Use it only to walk *recent* membership
> backward; rely on WRDS `idxcst_his` for the full 2009–2019 history.

## CSV export

The pipeline always writes the SQLite database. Pass `--export-dir DIR` to
*also* drop flat CSV files (openable in Excel / Stata / R / pandas) for the
deliverable tables:

```
out/firm_year_panel.csv
out/executive_year_panel.csv
out/exec_work_history.csv
out/exec_mobility.csv          # per-executive career-mobility features
out/exec_revelio_link.csv      # the scored match / review table
out/match_quality_report.txt   # the match-quality report (see below)
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
| `--funda` | gvkey × fyear | `gvkey, fyear, datadate, tic, cusip, cik, conm, sale, at, ni, ceq, dltt, capx, xrd, emp, naics, sic, sich` |
| `--index` | membership spell | `gvkey, gvkeyx, conm, indexname, from_date, thru_date` |
| `--constituents` | constituent | `ticker, cik, gvkey` (any one required) `+ company, index_name, from_year, thru_year` |
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
| `exec_mobility` | execid × user | per-executive career-mobility features (see below) |
| `firm_year_panel` | gvkey × year | **deliverable** — financials + NEO comp aggregates + matched-exec Revelio salary |
| `executive_year_panel` | execid × gvkey × year | **deliverable** — per-exec comp + the Revelio position active that year |

`exec_work_history` is the primary deliverable: for every matched executive it
contains *all* their Revelio position spells across *every* employer (prior,
non-universe firms carry a `NULL` gvkey), with seniority, role and modeled
annual salary.

## Executive-mobility features (`exec_mobility`)

Derived from the work history, one row per matched executive: `n_positions`,
`n_employers`, `max_seniority`, `n_exec_positions`, `career_start_year`,
`career_end_year`, `experience_years`, `n_prior_employers_before_focal`, and two
career-path flags relative to the *focal* firm (where Execucomp observed them):

* **`internal_promotion`** — their first spell at the focal firm was below
  executive seniority but a later focal spell reached it → rose through the
  ranks internally.
* **`external_hire`** — their first focal spell was already executive level and
  they had prior experience elsewhere → brought in from outside.

(Neither flag fires for a founder whose very first job was the focal exec role.)
Ongoing spells are closed at the latest year observed in the data so
`experience_years` is deterministic.

## Job category (`role_k7`)

Every Revelio position carries a **`job_category`** taking one of exactly seven
values — **admin, finance, marketing, sales, operations, scientist, engineer**
(Revelio's top-level `role_k7` taxonomy, normalized to these canonical labels).
It flows through:

- `exec_work_history.job_category` — the family of *each* career spell (so an
  executive's early junior roles are categorized too, not just the focal one);
- `executive_year_panel.revelio_job_category` — the category of the position
  active that year;
- `exec_mobility.primary_job_category` — the family of the executive's
  highest-seniority role (their "home" function).

In the WRDS extract, `wrds_extract.py` maps each position's `role_k1500` code to
`role_k7` via `revelio.individual_role_lookup_v2` (auto-detecting the key/label
columns; run `--list` to see them).

## Match-quality report

Every build prints — and `--export-dir` writes to `match_quality_report.txt` —
a summary to help you tune `--min-tier` and spot bad links:

```
Executives (NEOs)     : 5 (4 matched, 1 unmatched, rate 0.8)
Accepted by tier      : high=4, medium=0, low=0
Ambiguous pairs       : 0 (execid+gvkey with >1 accepted person -> review)
Salary ratio (rev/exec): n=4 min=1.373 median=1.478 max=1.622 outliers=0
Match rate by year    :
    2014: 4/5  (0.8)
    2015: 4/5  (0.8)
```

* **Ambiguous pairs** — accepted (execid, gvkey) with more than one Revelio
  person; review these before trusting the link.
* **Salary-ratio outliers** — best matches with Revelio/Execucomp salary ratio
  < 0.3 or > 3.0, a cheap signal of a mis-link.

## Configuration

Defaults live in `config.py` (all overridable):

* `MIN_FYEAR` / `MAX_FYEAR` — study window (2009–2019).
* `SP1000_INDEX_GVKEYX` — Compustat `gvkeyx` codes for S&P MidCap 400 +
  SmallCap 600. Confirmed WRDS values `024248` (MidCap 400) and `030824`
  (SmallCap 600); a direct "S&P 1000 Index" is `146884`. Override via
  `--index-gvkeyx` if needed. (The sample data uses these same codes.)
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
├── universe.py          # S&P 1000 / window / SIC filter (idxcst or list mode)
├── wrds_extract.py      # pull the six inputs from WRDS (run on your account)
├── wiki_parse.py        # Wikipedia S&P 400/600 page -> constituent / change CSV
├── reconstruct.py       # backward-reconstruct historical membership from changes
├── crosswalk.py         # gvkey <-> rcid (Revelio gvkey + ticker/cusip fallback)
├── matching.py          # executive <-> Revelio person matcher (scored/tiered)
├── workhistory.py       # complete work history of matched executives
├── mobility.py          # per-executive career-mobility features
├── panels.py            # firm-year + executive-year panels
├── jobcat.py            # 7-value job-category (role_k7) normalizer
├── report.py            # match-quality report
├── export.py            # optional CSV export of the deliverable tables
├── sample_data/         # runnable example inputs (6 CSVs)
└── tests/               # unittest suite
```
