# demand-on-demand: Project Plan (draft)

**Name:** `demand-on-demand` (folder and GitHub repo)
**Author:** Joseph M. Hahn, Ph.D., JMH DataSciences
**Drafted:** 2026-09-26

## 1. The pitch

A business user types:

> "Make a monthly forecast of Tito's vodka bottles sold across Polk County for the next 5 months."

A single Claude agent (Anthropic SDK, single agent with multiple tools) then does what a
data scientist would do by hand:

1. finds the relevant tables in a local enterprise-style database (NL2SQL schema discovery),
2. resolves fuzzy business terms against dirty data ("Tito's" matches 14 item descriptions; "Polk County" is spelled 3 ways),
3. writes and runs the aggregation SQL over millions of raw transactions,
4. profiles the result and proposes cleaning, gap-filling and outlier rules,
5. proposes candidate ML features and justifies them,
6. hands off to a **fixed, deterministic harness** that trains the model, grid-searches
   hyperparameters under a leakage-safe rolling-origin backtest, compares against a
   seasonal-naive baseline, and renders an HTML dashboard of predictions vs actuals.

The main design idea carries over from FDE03: **the LLM makes the judgment calls, and
deterministic code owns everything that has to be trustworthy.** Specifically, the LLM
never writes the train/test split, the metrics, or the dashboard.

### What's new vs FDE03 and chicago_crime_forecast

| | chicago_crime_forecast | FDE03 skill | **This project** |
|---|---|---|---|
| Runtime | scripts | Claude Code writes throwaway code | **Standalone app on Anthropic SDK** (no Claude Code needed at runtime) |
| Data access | Socrata API pull | Socrata API per request | **One-time load into a local DB; agent queries it with NL2SQL** |
| Data cleaning | hand-coded | minimal | **Agent profiles data and proposes rules; harness applies them and logs each one** |
| Features | calendar | calendar | **Agent-proposed exogenous features, tested by ablation** |
| Tuning | fixed | fixed | **Grid search under backtest** |
| Domain | crime | crime | **Retail demand (the most common business forecast)** |

Claude Code is the **build tool** (subscription tokens), and the Anthropic SDK is the
**runtime** (API tokens). Keeping those two roles separate is itself a LinkedIn talking point.

## 2. Dataset recommendation: Iowa Liquor Sales

**Recommendation: Iowa Liquor Sales**, which covers every wholesale liquor purchase by every
licensed Iowa retailer, 2012 to present.

Why it beats both candidates:

| Criterion | Chicago crime | Brooklyn property sales | **Iowa Liquor Sales** |
|---|---|---|---|
| Rows | ~8M | ~tens of thousands per year (NYC total ~1-2M) | **~30M+** |
| Business framing | public safety; sensitive, and needs a disclaimer | valuation (regression), not forecasting | **retail demand forecasting, instantly relatable** |
| "Object X" dimension | ~30 crime types | building class | **product hierarchy: category > vendor > item (thousands of SKUs)** |
| "Region Y" dimension | ward, district, beat | neighborhood | **store > city > zip > county (99 counties)** |
| Rich ML features | thin (time, location) | rich but static | **price, cost, margin, bottle size, pack, # active stores, new SKUs, holidays** |
| Dirty data | mild | moderate | **plenty: city/county casing and spelling variants, missing counties, category renames over time, store address drift, returns and negatives** |
| Novelty for you | already done twice | already blogged | **new, and a retail vertical to match your jewelry-retailer NL2SQL work** |

The dirt is a feature for this project, because it gives the AI cleaning and entity-resolution
steps real work to show.

**Enrichment tables** (small, loaded once) so NL2SQL has real joins to reason about:
- Census county population and median income (ACS), per year
- US federal holidays, plus Iowa-specific events (State Fair in August, football Saturdays)
- Optional: BLS county unemployment (LAUS) as a macro feature

**Runners-up**, if Iowa access is a problem:
- *NYC TLC trip records:* billions of rows, but a weaker "object X" dimension.
- *Favorita / M5 (Kaggle):* the license restricts redistribution, and the data is already clean. Not recommended.
- *UCI Online Retail II:* only about 1M rows over 2 years. Too thin.

**Data access (verified 2026-09-26):** `data.iowa.gov` moved from Socrata to the new "Iowa Data Hub",
so the old `m3tr-qhgy` URLs return 404. Data is now published as one dataset per year:
`https://idh-be.iowa.gov/api/v1/datasets/<id>/rows.csv` (a zip of CSV parts), with column defs at
`.../columns.json`. The 2025 dataset is id 1262 (659 MB, 3.04M rows) and 2026 year-to-date is id 1263.
Phase 0: look up the ids for 2016 through 2024 on catalog.data.gov. Fallback: BigQuery
`bigquery-public-data.iowa_liquor_sales.sales`.

**Observed in 2025 sample:** 23 columns; 2,243 stores, 5,048 items, 232 vendors, 48 categories,
473 cities, 99 counties. `state_bottle_cost` / `state_bottle_retail` are blank on 40% of rows.
The new portal has normalized casing in 2025, so most of the dirt should be in older years
(mixed-case cities, null counties, renamed categories). Check this in Phase 2.

## 3. Database: simulating the enterprise

**Decision: Postgres** (local, Homebrew), database `iowa_liquor`.
- It's the dialect Claude writes most reliably, and the database most readers recognize as "a real company DB."
- 30M rows is comfortable with the right indexes (date, store, item) and `COPY`-based loading.
- Readers reproduce it with `brew install postgresql@17` (or Docker) plus `python load_data.py`.

**Schema, deliberately warehouse-shaped** (so the agent has to *discover* the model):

```
raw.liquor_sales_raw         -- untouched landing table, all dirt preserved
sales.fact_invoice_line      -- lightly typed copy, still dirty values
sales.dim_store              -- store_id, name, address, city, zip, county (inconsistent)
sales.dim_item               -- item_id, description, pack, bottle_ml, category_id, vendor_id
sales.dim_vendor
sales.dim_category           -- category names change over the years
ref.county_demographics      -- ACS population / income by county-year
ref.calendar                 -- date, month, holiday flags, state-fair flag
```

Add column comments and a light data dictionary table (`meta.column_notes`), because
that's what a good enterprise DB offers and it's what NL2SQL depends on.

## 4. Runtime architecture (Anthropic SDK)

```
user request
   │
   ▼
[1] Spec parser (Claude, structured output) ── grain, horizon, target metric, object, region
   │
   ▼
[2] Agent loop (Claude + tools, read-only DB) ─────────────────────────────┐
     tools: list_tables · describe_table · sample_rows · profile_column    │
            find_values(fuzzy)  · run_select(sql, row_cap)                 │
     outputs: resolved entities, aggregation SQL, cleaning rules (JSON),   │
              candidate features (JSON) + one-line rationale each          │
   │                                                                       │
   ▼                                                                       │
[3] Governance harness (fixed Python, no LLM) ◀───────────────────────────┘
     validate SQL (sqlglot: SELECT-only, allowlisted schemas, row cap)
     apply cleaning rules from a closed vocabulary (map_values, drop_negatives,
       fill_gaps: zero|ffill|interp, cap_outliers: iqr|mad)
     build panel → feature ablation → grid search (skforecast + LightGBM)
       under rolling-origin backtest vs seasonal-naive baseline
     reliability label per horizon · prediction intervals
   │
   ▼
[4] Dashboard + narrative
     self-contained HTML: actuals vs backtest preds, forecast + intervals,
     metrics table, SQL used, cleaning log, feature ablation, agent trace
     Claude writes a short plain-English summary *grounded in the metrics JSON*
```

Key decisions:
- **The agent uses tools and does not exec arbitrary code.** Unlike FDE03, Claude never runs arbitrary Python. It emits SQL (validated) and declarative JSON specs (schema-checked). That makes it safer and auditable, and it's a good story for business readers.
- **Read-only DB connection** plus SQL AST validation. That's the guardrail story.
- **Models:** Sonnet 5 for the agent loop and Haiku 4.5 for cheap steps (spec parsing, summary). Use prompt caching on the schema and data-dictionary context. Log tokens and cost per run and show them on the dashboard, since business readers will ask about cost.
- **Clarify vs guess:** ambiguous region (Des Moines city vs Polk County) triggers one clarifying question. Otherwise the agent makes a reasonable guess and states it on the dashboard.
- **Refusals:** horizon too long for the available history, objects not in the data, or too little history to backtest.
- **Caching:** the panel and the fitted model are keyed by spec minus horizon (reused from FDE03), so "extend to 8 months" is instant.

## 5. Interfaces

- CLI: `python -m fod "monthly forecast of Tito's bottles sold in Polk County, next 5 months"`
- Optional thin Claude Code skill wrapper (`/forecast`) that calls the CLI, for the "works inside your AI assistant too" angle
- Optional later: a small Streamlit or FastAPI page for a demo video

## 6. Evaluation (what makes it credible)

- **Golden request set** (~20 requests) with expected entity resolution, for example "Tito's" → item IDs and "Polk" → county variants. Score it automatically in pytest. The requests span grain, region type, product level, and ambiguity.
- **Forecast quality:** MASE vs seasonal-naive at each horizon, reported honestly, including the requests where the model loses.
- **Agent robustness:** run each golden request 3 times and report how often the resolved SQL gives identical aggregates.
- **Showcase outputs:** 4 or 5 dashboards published on GitHub Pages.

## 7. Build phases (Claude Code sessions)

| Phase | Deliverable | Est. |
|---|---|---|
| 0 | Verify Iowa data access; `CLAUDE.md`; repo skeleton; venv; `.env` for `ANTHROPIC_API_KEY` | 0.5 day |
| 1 | `load_data.py`: one-time pull → Parquet → DuckDB star schema + ref tables + data dictionary | 1 day |
| 2 | `explore_data.py` dashboard documenting the dirt (this becomes blog material) | 0.5 day |
| 3 | Governance harness: panel → backtest → grid search → baseline → dashboard, driven by a *hand-written* spec (no LLM yet) | 1.5 days |
| 4 | Agent: tools, SQL validator, spec parser, cleaning/feature JSON schemas, agent loop | 2 days |
| 5 | Golden-set evals and fixes; cost and latency logging | 1 day |
| 6 | Showcase runs → GitHub Pages; README with "About the author" block; MIT license; CITATION.cff | 0.5 day |
| 7 | Blog write-up plus LinkedIn post series | 1 day |

Build the harness before the agent (phase 3 before 4). That way the ML is proven correct on
its own, and the agent is only responsible for choosing *what* to forecast.

## 8. GitHub and LinkedIn plan

- **Repo README** leads with a GIF: type a request, and a dashboard appears. Include the architecture diagram above, a "what the LLM decides vs what code guarantees" table, and a cost per forecast.
- **LinkedIn series (3 to 4 posts, about 1 per week):**
  1. "I asked for a forecast in plain English. Here's what the AI had to figure out first." (the dirty-data and entity-resolution story; show the 14 spellings)
  2. "Where I let the LLM decide, and where I didn't." (the governance split; the most shareable idea)
  3. "The model lost to a naive baseline on 3 of 20 requests. Here's why that's in the README." (the honesty and credibility post)
  4. "Built with Claude Code, runs on the Claude API: what that cost." (a tokens and dollars breakdown)
- Every post links to the repo. The repo's "About the author" block and every dashboard footer link to jmh-datasciences.com.
- Add a project card to the jmh.datasciences site (`publications/` or the portfolio section).
- Writing style: no em dashes in narrative text. Describe it as a single agent with multiple tools, never "multi-agent". NL2SQL is not RAG.

## 9. Open questions to settle

1. ~~Dataset~~: Iowa Liquor Sales (pending freshness check).
2. ~~Database~~: Postgres (local, via Homebrew).
3. ~~History~~: 2016 onward (about 30M rows, about 6.5 GB of CSV).
4. ~~Targets~~: all three (sales_bottles, sales_dollars, sales_liters).
5. ~~Name~~: `demand-on-demand`.
6. Local Python is 3.9.6. Install 3.12 via Homebrew or uv (current skforecast needs 3.10+).
