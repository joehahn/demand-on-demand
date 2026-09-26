# CLAUDE.md
**Author:** Joe Hahn  
**Email:** jmh.datasciences@gmail.com  
**Date:** 2026-September-26 <br>
**branch** main

## Project

demand-on-demand: a business user asks in plain English for a forecast
("monthly forecast of Tito's bottles sold in Polk County for the next 5 months")
and a single Claude agent (Anthropic SDK, one agent with several tools) finds the
relevant tables, resolves fuzzy business terms, writes the aggregation SQL, and
proposes cleaning rules and features. A fixed, deterministic Python harness then
trains, grid-searches, backtests against a seasonal-naive baseline, and renders an
HTML dashboard of predictions vs actuals.

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

## Ground rules

- The LLM decides *what* to forecast; deterministic code owns the split, metrics,
  baseline, cleaning execution, and dashboard. Never let generated code touch those.
- The agent's DB access is read-only and every SQL statement is validated (sqlglot, SELECT-only).
- Always write simple code that is well commented and understood at a glance.
- Writing style for README, blog, and posts: no em dashes in narrative text; describe the
  agent as a single agent with multiple tools (never "multi-agent"); NL2SQL is not RAG.

## Build phases

0. Setup: repo, env, Postgres, dataset ids (done)
1. `load_data.py`: one-time pull into a Postgres star schema + ref tables + data dictionary (done)
2. `explore_data.py`: dashboard documenting the dirt -> `docs/data_exploration.html` (done; `--fresh` re-queries)
3. Governance harness driven by a hand-written spec (no LLM)
4. Agent: tools, SQL validator, spec parser, cleaning/feature schemas
5. Golden-set evals, cost and latency logging
6. Showcase runs to GitHub Pages, README
7. Blog and LinkedIn series
