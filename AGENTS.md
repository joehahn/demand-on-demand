# AGENTS.md

Instructions for AI coding assistants working in this folder (the same rules Claude Code reads in CLAUDE.md).

demand-on-demand turns a plain-English request into a tested demand forecast and an HTML dashboard over a Postgres
warehouse of Iowa liquor sales. Inside the app, a single Claude agent (the forecasting agent) writes the SQL; fixed
Python code does the sums, models, backtests and dashboard. Your job as the assistant is to pass requests to it, answer
quick data questions read-only, and build follow-up charts from its saved results.

## Answering requests

**A plain-English forecast request** (e.g. "Monthly Fireball mini bottles at Casey's stores vs Hy-Vee stores, next 6
months"): do not answer it yourself, write SQL or build models. Run the app on the request, word for word:
`.venv/bin/python -m dod.forecast "<request>"` (about 30 seconds). Its last line is the dashboard's path: open it in
the browser (`open` on macOS), then reply in two or three sentences with the summary from that folder's summary.json
(`agent.summary`) and the path. If it prints `no_forecast` or an error, relay that message instead.

**A plain data question that is not a forecast** (e.g. "show total liquor sales by year for the Hy-Vee stores in
Ankeny"): answer it with one read-only query through the app's agent login: `from dod import db; db.query(sql)` (never
an owner or administrator login), using the clean tables as the data dictionary describes them (products by
family_item_no, categories by category_current, places by sales.store). Show the result as a short table and say what
it shows; build no forecast. If a year is incomplete, say so. If the question asks for a chart (e.g. "plot mean
Tito's dollars by month of year"), draw it from that query's result, not a second query: a short plotly script that
saves out/lookups/<name>.html using `dod.viz.page` and `style`, open it, and say in one sentence what it shows.

**A follow-up asking for a custom chart or number about a forecast already made** (e.g. "plot annual sales with this
year's actuals plus forecast"): answer it from that forecast's saved results, not by forecasting or querying again.
`from dod.results import load, latest` gives its actual and forecast tables (`latest()` is the newest forecast). Write
a short plotly script that saves out/<slug>/custom_<name>.html using `dod.viz.page` and `style`, open it, and say in
one sentence what it shows and that the numbers are the dashboard's.

## Environment and safety

- Python: `.venv/bin/python` (3.12). Database settings are read from `.env` by the app's code.
- Never print or reveal `.env`, `~/.pgpass` or any connection string or password.
- The app's database login is read-only; do not use any other login for answering requests.
- Write plain text without em dashes.
