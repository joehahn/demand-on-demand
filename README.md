# demand-on-demand

**Ask for a demand forecast in plain English; get a validated forecast and dashboard in about a minute.**

> Work in progress. The full write-up, example dashboards and results are coming; this repo is being built in
> public with [Claude Code](https://claude.com/claude-code).

A single Claude agent (Anthropic API) turns a request like *"monthly forecast of Tito's minis in Des Moines for
the next 5 months"* into a precise spec against a local Postgres warehouse of 26 million Iowa liquor orders
(2016 to 2026). A fixed Python harness then trains and tunes the models, backtests them honestly against a
"same month last year" baseline, and publishes a dashboard of predictions vs actuals.

- `load_data.py`: one-time pull of the public data into Postgres, including a clean stage that fixes the
  known data problems once, in the warehouse
- `explore_data.py` -> `docs/data_exploration.html`: what is wrong with the raw data
- `data_fixes.py` -> `docs/data_fixes.html`: what was fixed, before and after
- `dod/`: the agent (`dod/agent.py`) and the forecasting harness
- `evals/`: agent evals and summary-grounding checks

By Joseph M. Hahn, Ph.D., [JMH DataSciences](https://jmh-datasciences.com) ·
[LinkedIn](https://www.linkedin.com/in/hahnjoe/)

**Data:** [Iowa Liquor Sales](https://catalog.data.gov/dataset/iowa-liquor-sales), State of Iowa, via the Iowa
Data Hub, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); modified (duplicates removed,
cleaned, aggregated). County population and income: U.S. Census Bureau. Not endorsed by the State of Iowa.
Raw data is not stored in this repo; `load_data.py` downloads it.

**License:** [MIT](LICENSE)
