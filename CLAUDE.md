# CLAUDE.md
**Author:** Joe Hahn  
**Email:** jmh.datasciences@gmail.com  
**Date:** 2026-September-26 <br>
**branch** main

## Project

demand-on-demand: a business user asks in plain English for a forecast
("monthly forecast of Tito's bottles sold in Polk County for the next 5 months")
and a single Claude agent (Anthropic SDK, one agent with several tools) resolves fuzzy
business terms and writes one SQL query that picks the order lines to forecast, plus a
plain description of the request (grain, horizon, measure). Fixed, deterministic Python
then adds the lines up, builds the inputs, trains, grid-searches, backtests against a
seasonal-naive baseline, and renders an HTML dashboard of predictions vs actuals.

Claude Code is the build tool. The Anthropic SDK is the runtime; the app never
needs Claude Code to run. See `PLAN.md` for the full design.

GitHub: https://github.com/joehahn/demand-on-demand (not yet created)

## Environment

- Python 3.12 venv at `.venv/` (Dropbox-ignored): `.venv/bin/python`
- Postgres 17 via Homebrew, database `iowa_liquor`: `/opt/homebrew/opt/postgresql@17/bin/psql -d iowa_liquor`
  (DBA login `joehahn`, password in `~/.pgpass`)
- Settings and secrets in `.env` (chmod 600, gitignored; template in `.env.example`)

## Database access (small-business style)

- Password auth only (`scram-sha-256` in `pg_hba.conf`; the Homebrew `trust` default is backed up
  as `pg_hba.conf.bak-trust`). Listens on localhost only.
- Roles:
  - `joehahn`: superuser / DBA, for admin only.
  - `dod_owner`: owns the database and the schemas `raw`, `sales`, `ref`, `meta`. Used by the loader.
  - `dod_agent`: SELECT on `sales`, `ref`, `meta` only (default privileges cover future tables).
    No access to `raw`, no temp tables. Role defaults: read-only transactions, 60s statement
    timeout, search_path `sales, ref, meta`, max 5 connections.
- The LLM never sees credentials. DSNs are read from `.env` by Python tool code only; never put
  a DSN, password, or connection error text containing them into a prompt or tool result.
- Defense in depth: sqlglot SELECT-only validation in the tool, then Postgres grants
  (verified 2026-09-26: INSERT, DROP, CREATE, temp tables, pg_authid, pg_read_file all denied,
  even with read-only mode switched off in the session).
- Never print `.env` or `~/.pgpass` contents, including in Claude Code sessions.
- Raw downloads go to `$DOD_DATA_DIR` (default `~/data/demand-on-demand`), never into this Dropbox folder

## Data

Iowa Liquor Sales, 2016 onward, one Iowa Data Hub dataset per year:
`https://idh-be.iowa.gov/api/v1/datasets/<id>/rows.csv` (returns a zip of CSV parts, latin-1).

| year | id | year | id |
|---|---|---|---|
| 2016 | 1253 | 2022 | 1259 |
| 2017 | 1254 | 2023 | 1260 |
| 2018 | 1255 | 2024 | 1261 |
| 2019 | 1256 | 2025 | 1262 |
| 2020 | 1257 | 2026 YTD | 1263 |
| 2021 | 1258 | | |

Forecast targets: `sales_bottles`, `sales_dollars`, `sales_liters`.

Load: `.venv/bin/python load_data.py` (all stages; about 20 minutes, database about 13 GB).

Warehouse (built 2026-09-26, orders 2016-01-04 to 2026-08-31):
- `raw.liquor_sales`: 27.9M rows, text, exactly as published (agent cannot read it)
- `sales.invoice_line` (26.4M lines, PK `line_id`), `sales.store` (3,199), `sales.item` (13,443),
  `sales.vendor` (492), `sales.category` (108)
- `ref.calendar`, `ref.county_population` (2016-2025), `ref.county_income` (SAIPE, 2016-2024)
- `meta.column_notes` plus Postgres COMMENTs

Known source issues (found while loading):
- The 2022, 2025 and 2026 exports repeat ~1.5M rows verbatim across CSV parts (2022 would be
  inflated ~23%). The loader drops exact duplicates; the portal's own 2026 row count matches.
- `invoice_id` changed meaning on 2025-09-01: before, one id per line; after, one id per order.
  Prices are filled from the same date, so the state likely switched source systems.
- `state_bottle_cost` / `state_bottle_retail` are blank on every line 2016-2024 (filled from 2025-09).
- County is blank on ~4% of 2016 lines; 18 stores have no county in `sales.store`; 17 stores changed
  county over time (462 changed name, 272 changed address).
- Category taxonomy reorganized ~2016-08-29: ~96 names became ~47 and many codes were reassigned to
  different categories (e.g. 1011400 Bottled in Bond Bourbon -> Tennessee Whiskies). Names shortened 2025-07.
- Since 2022, 1-4k lines/year have zero bottles and zero dollars (likely cancelled lines).
- A sleeve or pack of minis is one "bottle" (Tito's mini 38194 = sleeve of 12 at $19.20). Until mid-2019 (and some packs
  until 2025-08) volume was recorded as the sleeve total (600 ml), then as one mini (50 ml). Clean stage: `sales.item_units`
  (172 items with known pack size -> sales_bottles counts minis; 814 priced like packs but size unknown -> flagged, left in
  selling units). Originals kept in `sales_bottles_recorded`, `sales_liters_recorded`, `bottle_volume_ml_recorded`.
- Liters were truncated to whole liters Nov 2025 - Jan 2026 (405k lines); clean stage sets liters = bottles x volume.

## Ground rules

- The LLM decides *what* to forecast; deterministic code owns the split, metrics,
  baseline, cleaning execution, and dashboard. Never let generated code touch those.
- The agent's DB access is read-only and every SQL statement is validated (sqlglot, SELECT-only).
- Always write simple code that is well commented and understood at a glance.
- Writing style for README, blog, and posts: no em dashes in narrative text; describe the
  agent as a single agent with multiple tools (never "multi-agent"); NL2SQL is not RAG.

## Build phases

Demo scope (decided 2026-09-27): known data issues are documented (explore page) and fixed once in the warehouse
(`load_data.py clean`, `docs/data_fixes.html`); forecasts read only clean data. The demo's focus is fast, easy,
accurate forecasts on request. No runtime issue discovery (register, slice checks and onboarding were removed).

0. Setup (done)
1. `load_data.py`: download, raw, curate, ref, clean, meta (done)
2. `explore_data.py` -> docs/data_exploration.html; `data_fixes.py` -> docs/data_fixes.html (done)
3. Harness `dod/` (done): history (fixed sums around the agent's SQL) -> model (grid on tuning window, seasonal naive
   as a candidate, rolling-origin test) -> dashboard. `python -m dod.forecast "<request>"`
4. Agent `python -m dod.agent "<request>" [--sql-only]`: find_values, run_select, ask_user, submit_query
   (phases 4-11 below describe the earlier slot-filling agent, retired 2026-10-03; see 14)
5. Evals (done): `python evals/run_evals.py` 42/42 correct (21 cases, 2026-09-30), $0.016 and ~20 s per request, 4 tool calls;
   `python evals/grounding.py` 60/60 summaries grounded (2026-10-01; summary = one AI sentence + one code sentence).
6. Accuracy and speed (done): parallel fits (LightGBM n_jobs=1), products resolved to item lists (indexed),
   pooling with 15 companion counties as a grid option, single-best or top-3 average blended with seasonal
   naive (chosen on the tuning window). ~15-20 s per forecast; end to end from plain English ~40 s (median of the examples, 2026-09-30).
   `python benchmark/run_benchmark.py`: beats same-month-last-year on 23 of 30 sampled forecasts, median
   relative error 0.88, median WAPE 15.0% vs 16.0% (rerun 2026-09-29 after the mini-units fix).
7. Showcase (done 2026-09-27): https://joehahn.github.io/demand-on-demand/ (GitHub Pages from docs/):
   `showcase.py` -> docs/index.html; three example dashboards in docs/examples/ (Tito's minis, Fireball revenue, holiday cream liqueur; generated by the agent from
   plain-English requests; index.json holds their summaries); README; drafts in blog/ (blog_post.md,
   linkedin_posts.md). Not yet posted anywhere.
8. Demo (2026-09-30): `python demo.py` runs canned requests from demo/requests.json live (`--rehearse`, `--replay`,
   `--check`); the 7 requests are tagged "demo" in evals/cases.json. Big-buyer split experiment: not adopted
   (benchmark/big_buyers.md); dashboards name a store with > 25% of the last 12 months instead.
   Finer hyperparameter grids not adopted: 288 configs (benchmark/grid_experiment.md: 20 vs 23 of 30, median 0.931 vs
   0.880, 2x slower) and 192 configs (grid_experiment_middle.md: 20 vs 23, median 0.920, 1.4x slower).
9. NL2SQL prototype (2026-10-01): `dod/nl2sql.py` (same agent and tools, writes the series SQL itself);
   `python evals/differential.py` compares it with slot filling month by month; `evals/differential_report.py` ->
   docs/differential.html. First run found a reference bug (find_values showed at most 60 products: Crown Royal 91,
   Jack Daniel's 80); fixed 2026-10-02 with product kind "name" (one brand's words, resolved by panel.member_items) and
   a "N products match" note in find_values. After the fix: 11/18 identical, 7 AI-written queries wrong (renumbered
   items, recorded category codes, brand-prefix matches), all on the AI side; evals 42/42. With three explicit rules
   (dod/nl2sql.RULES, `differential.py --rules`): 17/18 (the miss: a brand matched as one phrase).
10. On-the-fly forecasts by week / month / quarter / year (2026-10-02, prototype): `dod/onthefly.py` (AI writes SQL for
   DAILY totals + grain + horizon + an optional request-form fill; fixed code buckets, runs model.run under
   `model.use_grain(...)` (season 52/12/4, windows 2 seasons, weekly refit every 4 weeks; parallel jobs get the grain via
   `model.in_grain`), and cross-checks daily-summed-by-month vs the slot-filling series). Monthly path verified identical.
   `python evals/onthefly_report.py` -> docs/onthefly.html: 4 of 5 cross-checks passed; the Hy-Vee group one failed
   because the store search showed 40 of 207 stores (store search now says "N stores match").
11. Full dashboards at any grain (2026-10-02): Spec.grain (month default; week/quarter, horizon <= 52/4); dashboard.py
   reads grain words via set_grain/when/stamp/back/base; build(..., ai={sql, check}) gives the on-the-fly variants
   (AI wrote the SQL; cross-check; tables read by its query). onthefly.forecast writes out/<slug>/dashboard.html when the
   AI filled in the request form. Example: docs/examples/cream_liqueur_by_week_next_12_weeks.html. Monthly pages verified
   identical in numbers; fixed a stray "and 23 more" (variable clash) on the published cream liqueur page.
12. Inputs (2026-10-02): weekly forecasts are offered season, holiday weeks and active stores (`dod/features.py`;
   benchmark/features.md: weekly median 0.857 -> 0.826, 29/30). Each group is kept if it helps at all on the
   model-selection window; a 2% or 5% keep margin was worse (benchmark/margin.md: median 0.849 / 0.854). Dashboards
   show "Which inputs helped" (model.run "effects": error without each group vs with it, selection window and Test
   period, the Test side scored like the final blend).
13. Answer key for AI-written SQL (2026-10-02; first step to retiring slot filling): evals/answer_cases.json (34 requests:
   the 21 eval cases + 13 new weekly/quarterly/year, brand, category and store-group requests; hand-reviewed request
   forms, a "definition" where a person had to choose, 3 expected refusals); `python evals/build_answers.py` ->
   evals/answers.json (correct monthly totals from the fixed SQL; reproduces the differential test's 18 references).
   `python evals/score_sql.py` scores the AI-written-SQL agent (dod/onthefly.ask) against it, 3 runs each: baseline
   90/102 (every miss a definition, none a warehouse trap); with the business glossary (dod/nl2sql.GLOSSARY: brands
   include flavors, spirit types include flavored categories but not liqueurs and are selected by category name, sizes
   by bottle size, event periods through their end) 101/102, data right in 102/102 (2026-10-02, $1.84).
14. One path (2026-10-03): slot filling retired. The agent (dod/agent.py) writes SQL returning one row per order line
   (day, store_no, item_no, series, value) plus a Plan (dod/plan.py: title, measure, product, place, breakout, grain,
   horizon). Fixed code (dod/history.py) never runs it as is: it wraps it in sums by month/store/series, by week/series
   and distinct items, which feed the series, store list and map, active stores, population (counties of the series'
   stores) and data-prep notes. Inputs by grain (dod/features.GROUPS): weeks season, holiday_weeks, stores; months
   calendar, population. Quarters and years are forecast by month ("next quarter" = next 3 months; calendar quarters
   would include months already known). No pooling (benchmark/pooling.md). dod/forecast.py runs it end to end.
   Removed: dod/run.py, dod/onthefly.py, dod/nl2sql.py, specs/, evals/run_evals.py, evals/differential.py, the per-request
   cross-check. Kept as test tooling: dod/spec.py + dod/panel.py (reference_sql for the benchmark, build_sql for the
   answer key). Results: evals/score_sql.py 101/102 (one Diageo miss, then a vendor definition added: 3/3);
   benchmark 20/30 beat last year, median 0.91 (= the no-pooling arm). `python make_examples.py` regenerates
   docs/examples/ and index.json.
15. Agent told where the data ends (2026-10-06): SYSTEM includes the last order date (panel.data_end), so "for the
   holidays" counts from September; glossary adds "a vendor's products = the lines it sold". evals/score_sql.py:
   102/102 (34/34 every run, $1.79). Dashboards say "sales records" (not order lines) and read the Tested sentence from
   the latest full evals/sql_results/2*.json (runs with --only are saved as only_*.json).
16. Choose twice (2026-10-06): model.run calls choose() on the validation window (the tested choice, scored on the
   Test period: the accuracy figures) and again on the latest two years (the forecast's choice), so decisions use the
   most recent data and the reported accuracy stays honest (it measures the procedure). Dashboards name the periods
   Validation / Test / Forecast; Figure 4 shows each input's effect in both choices. Fixed a leak: active stores in
   backtests counted orders after the starting point; now shifted back by the forecast horizon (features.stores lag).
   Holiday weeks match exact names (Juneteenth was flagged as July 4th week).

