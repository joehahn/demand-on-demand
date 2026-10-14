# How the forecasting agent got there

**From a request form to AI-written SQL.** An earlier version had the AI fill in a request form (product, place,
measure, months) and fixed code write the SQL from it (slot filling). To retire the form, the AI was asked to write
the SQL itself, and the two were compared month by month on the same requests
([differential report](https://joehahn.github.io/demand-on-demand/differential.html)).

**Three warehouse traps, three rules.** The comparison found that every disagreement was a mistake in the AI-written
SQL, and that they came from three traps in the warehouse: products that were renumbered, categories whose codes were
reassigned, and brand names that match other brands with extra words. Three short rules in the agent's instructions
fixed them (11 of 18 requests identical before the rules, 17 of 18 after).

**An answer key, then a glossary.** A hand-checked answer key ([evals/sql_report.md](evals/sql_report.md)) then scored
the agent's SQL on 34 requests, 3 runs each. The baseline was 90 of 102. Every remaining miss turned out to be a
business definition, not a SQL error (for example, whether "minis" means 50 ml bottles, or whether whiskey includes
whiskey liqueur), so a short glossary of the company's definitions was added to the agent's instructions. With the
glossary, and the agent also told where the data ends, the score is 102 of 102.

**Pooling dropped.** Measured before slot filling was retired: training each county's model together with other
similar counties (pooling) added little and unevenly ([benchmark/pooling.md](benchmark/pooling.md)), so it was dropped.
