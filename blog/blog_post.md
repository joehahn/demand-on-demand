# Ask for a forecast in plain English, get a tested answer in 30 seconds

*Draft. Joseph M. Hahn, Ph.D., JMH DataSciences*

Most businesses that live on forecasts still build them by hand. Someone gets a request ("what will Tito's minis
do in Des Moines over the holidays?"), finds the right product codes, writes the query, pulls the numbers into a
spreadsheet, fits something, and a few days later sends back a chart with no clear sense of how far to trust it.

I wanted to see how much of that an AI agent can take over, and how to do it without handing the trust-critical
parts to a language model. The result is
[demand-on-demand](https://joehahn.github.io/demand-on-demand/): you type a question in plain English, and about
30 seconds later you get a forecast, an 80% range, and a plain statement of how accurate that kind of forecast has been.
Each request costs about two cents of Claude API usage.

## The setup: a realistic company database

The demo runs on public data that behaves like a real sales database: every wholesale liquor order placed by an Iowa
retailer, published by the State of Iowa. I loaded ten years of it, 2016 to 2026, into a local Postgres warehouse:
26 million order lines across 3,200 stores and 13,000 products, plus Census population and income by county.

It is set up the way a small company would do it: password logins, a loader role that owns the tables, and a
read-only role for the agent that cannot see the raw landing tables and has a query time limit. The agent never sees
a credential. Its tools run inside Python, which holds the connection.

## First, the data had to be fixed

Before any forecasting, I profiled the data, and it had problems that would quietly ruin a forecast:

- **The state's own export duplicated 1.5 million rows.** The 2022, 2025 and 2026 downloads repeat rows verbatim
  across files. Left in, 2022 sales look 23% higher than they were.
- **Category codes changed meaning.** In August 2016 the state reshuffled its product categories, so a code that
  meant "Bottled in Bond Bourbon" one week meant "Tennessee Whiskies" the next. In 2022 the ready-to-drink cocktail
  category moved to a new code, so on the old code it looks discontinued.
- **254 products were renumbered.** Same product, new item number, the history split in two.
- **Cities are spelled several ways**: MT PLEASANT and MOUNT PLEASANT, CLEARLAKE and CLEAR LAKE.

My first design had the AI agent discover and fix these problems for every request. It worked, and it was
impressive, but it made every forecast slower, costlier and harder to explain. So I moved the fixes where they belong:
into the warehouse, once, at load time. Duplicates and cancelled lines are removed, renumbered items are joined into
product families, all ten years are restated in today's categories, and each city has one spelling. The
[data exploration page](https://joehahn.github.io/demand-on-demand/data_exploration.html) documents each problem,
and the [data fixes page](https://joehahn.github.io/demand-on-demand/data_fixes.html) shows before and after. After
that, no forecast has to know these problems existed.

## Where the AI decides, and where it doesn't

The design principle is simple: **the AI decides what to forecast; fixed code decides how.**

A single Claude agent (Claude Sonnet 5, through the Anthropic API) gets the request and five read-only tools: search
product and place names, run one checked SELECT, preview a draft request, ask one clarifying question, and submit.
For "monthly forecast of Tito's minis in Des Moines for the next 5 months" it searches for Tito's, sees that "minis"
means the 50 ml products, finds the city of Des Moines, previews the monthly series to confirm there is enough
history, and submits a small structured spec: product codes, place, measure (bottles), horizon (5 months). That takes
about four tool calls and fifteen seconds.

What it never does is write the aggregation SQL, choose the train/test split, compute the accuracy, or draw the
charts. Those are fixed Python code, identical for every request, and they are where a forecast earns or loses trust.
A second, short Claude call writes the two-sentence summary at the top of the dashboard, and it may only use numbers the
harness computed. A check confirms every number it writes can be traced back to them.

## Honest accuracy

Every forecast is scored the same way. The last 24 months are held back as a test the model never sees. Model
settings are tuned on the two years before that: 96 configurations of LightGBM and ridge regression, modeling the
monthly level, the month-over-month change, or the change from the same month last year, with or without learning from
the same product in other counties. Then the harness picks the single best configuration or the average of the top
three, and blends it with a simple benchmark: "the same month last year."

That benchmark matters. Iowa liquor demand is extremely regular: October is the peak month every year, December is
low because stores stocked up already, and since 2023 each year looks much like the last. "Same month last year" is
a hard baseline to beat, and the harness only lets a model take over as far as it beats it on data it hasn't seen.

On a benchmark of 30 forecasts sampled from the warehouse (products, categories and vendors; counties and statewide;
bottles, dollars and liters; 3 to 12 months ahead), the model beat that baseline on 23, with a median error 12% lower
(15.0% monthly error versus 16.0%). On the other 7 it did not, and the
[benchmark report](https://github.com/joehahn/demand-on-demand/blob/main/benchmark/report.md) lists every one of
them. The dashboard for each forecast says which case you are in.

The agent was tested separately: 19 requests, run twice each, including ones it should decline (a city outside
Iowa, a 24-month horizon, a product too new to forecast). It got all 38 runs right.

## What I learned

1. **Put data fixes in the data, not in the AI.** The agent was capable of spotting a renumbered product and fixing
   it on the fly, but a fix you apply once in the warehouse is cheaper, faster, and the same for everyone.
2. **Keep the language model on the part people find tedious.** Turning "Tito's minis in Des Moines next quarter"
   into codes is exactly that part. Deciding whether a model is good enough is not.
3. **Compare against a baseline you can explain in one sentence.** "Better than repeating last year" is a claim a
   business owner can check. It also kept me honest: my first models lost to it.
4. **Speed came from engineering, not a bigger model.** Pinning each model fit to one CPU thread and running fits in
   parallel took a forecast from 90 seconds to about 15.

This was built with Claude Code, which wrote most of the code while I directed the design and checked the results.
The code, the evals, the benchmark and the example dashboards are on
[GitHub](https://github.com/joehahn/demand-on-demand).

If your business still builds forecasts by hand, or you want AI that answers questions from your own database without
guessing, that is the work I do at [JMH DataSciences](https://jmh-datasciences.com).
