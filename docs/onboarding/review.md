# Proposed known-issues register

Drafted by `claude-opus-5` in 191.4s, 11,353 in / 18,071 out tokens, about $0.51.


## warehouse

### raw_export_duplicate_rows: 1.51M verbatim duplicate rows in the 2022/2025/2026 portal exports (de-duplicated by the loader)
- severity: medium; scope: sales.invoice_line [line_id, invoice_id, ordered_on]; dates: 2022-01-01 to 2026-08-31
- raw.liquor_sales has 27,947,018 rows; sales.invoice_line has 26,434,053 after dropping 1,512,965 exact duplicate rows. The duplication is concentrated in the yearly CSV exports for 2022, 2025 and 2026, where CSV parts repeat rows verbatim. Worst months: 2025-08 (314,836 published vs 204,260 distinct), 2025-09 (412,324 vs 206,158), 2025-10 (429,632 vs 214,815), 2025-11 (219,938 vs 195,311), 2026-07 (380,372 vs 217,782), 2026-08 (403,112 vs 201,555); 2025-12, 2026-03 and 2026-06 differ by only 1-12 rows. The portal's own 2026 row count matches the distinct count, so de-duplication is correct. Residual risk (hypothesis, not proven): a genuinely repeated order line (same invoice, item, date, price and quantity) would also have been collapsed, which would shave a small amount of volume off exactly those months.
- impact: If the raw feed were used instead, monthly bottles/dollars for 2025-08..2025-11 and 2026-07..2026-08 would be inflated by 10-100%. Using sales.invoice_line the problem is gone, but a forecaster should still sanity-check those months for a small downward level shift from over-collapsed legitimate repeats.
- fix: `etl_fixed` {}
- evidence check: **ran** 
```sql
SELECT date_trunc('month', ordered_on)::date AS month, count(*) AS lines, sum(sales_bottles) AS bottles FROM sales.invoice_line WHERE ordered_on >= DATE '2025-06-01' GROUP BY 1 ORDER BY 1
```
first rows: 2025-06-01, 219158, 2642511; 2025-07-01, 210029, 2542822; 2025-08-01, 204260, 2550030; 2025-09-01, 206158, 2550832; 2025-10-01, 214815, 2778821

### invoice_id_semantics_change_2025_09: invoice_id changes meaning in 2025-09: one line per invoice before, ~19-21 lines per invoice after
- severity: high; scope: sales.invoice_line [invoice_id, line_id]; dates: 2025-09-01 to 2026-08-31
- Through 2025-08 the ratio lines / distinct invoice_id is exactly 1.000000 every month, i.e. the source emitted a unique invoice id per order line. From 2025-09 onward the ratio jumps to 19.1 (2025-09), 20.2, 20.1, 21.0, and stays in the 18.8-20.0 range through 2026-08 - the source system began issuing one invoice id per order covering many lines. invoice_id is also not unique in the warehouse at all; line_id is a surrogate key created by the loader.
- impact: Any metric keyed on invoice_id (order counts, lines-per-order, dedup by invoice) breaks with a ~20x artificial drop in 'orders' at 2025-09, which a model will read as a collapse in demand. Bottles/dollars/liters totals are unaffected.
- fix: `use_line_id` {}
- evidence check: **ran** 
```sql
SELECT date_trunc('month', ordered_on)::date AS month, count(*) AS lines, count(DISTINCT invoice_id) AS invoices, round(count(*)::numeric / count(DISTINCT invoice_id), 3) AS lines_per_invoice FROM sales.invoice_line WHERE ordered_on >= DATE '2025-01-01' GROUP BY 1 ORDER BY 1
```
first rows: 2025-01-01, 200509, 200509, 1.000; 2025-02-01, 176352, 176352, 1.000; 2025-03-01, 195133, 195133, 1.000; 2025-04-01, 211280, 211280, 1.000; 2025-05-01, 211097, 211097, 1.000

### bottle_price_columns_null_before_2025: state_bottle_cost and state_bottle_retail are 100% NULL before 2025 and 40% NULL in 2025
- severity: high; scope: sales.invoice_line [state_bottle_cost, state_bottle_retail, sales_dollars, sales_bottles]; dates: 2016-01-01 to 2025-12-31
- Blank-rate profiling shows state_bottle_cost and state_bottle_retail are NULL on 100% of lines for 2016 through 2024, on 39.83% of 2025 lines, and on 0% of 2026 lines. The source only started publishing per-bottle prices partway through 2025. sales_dollars and sales_bottles are populated throughout.
- impact: Price-based features, elasticity terms or revenue rebuilt from price*quantity are unavailable before 2025 and half-missing in 2025; any model conditioned on them would silently train on 2026 data only. Filtering on a non-null price column would drop nearly the entire history.
- fix: `derive_price` {}
- evidence check: **ran** 
```sql
SELECT extract(year FROM ordered_on)::int AS yr, count(*) AS lines, round(avg(CASE WHEN state_bottle_retail IS NULL THEN 1 ELSE 0 END), 6) AS null_retail_frac, round(avg(CASE WHEN state_bottle_cost IS NULL THEN 1 ELSE 0 END), 6) AS null_cost_frac FROM sales.invoice_line GROUP BY 1 ORDER BY 1
```
first rows: 2016, 2279893, 1.000000, 1.000000; 2017, 2291276, 1.000000, 1.000000; 2018, 2355558, 1.000000, 1.000000; 2019, 2380345, 1.000000, 1.000000; 2020, 2614365, 1.000000, 1.000000

### category_code_reassignment_aug_2016: Category codes were wholesale reassigned to different products on 2016-08-29
- severity: high; scope: sales.invoice_line, sales.category [category_code, category_name]; dates: 2016-01-04 to 2016-08-31
- At least 20 category codes carry one meaning up to 2016-08-26 and a different meaning from 2016-08-29 onward: 1011300 TENNESSEE WHISKIES -> SINGLE BARREL BOURBON WHISKIES, 1011400 BOTTLED IN BOND BOURBON -> TENNESSEE WHISKIES, 1011500 STRAIGHT RYE -> BOTTLED IN BOND BOURBON, 1011600 CORN WHISKIES -> STRAIGHT RYE, 1012300 IRISH -> SINGLE MALT SCOTCH, 1012400 JAPANESE WHISKY -> IRISH, 1022100 TEQUILA -> MIXTO TEQUILA, 1031100 100 PROOF VODKA -> AMERICAN VODKAS, 1031200 VODKA FLAVORED -> AMERICAN FLAVORED VODKA, 1032200 IMPORTED VODKA-MISC -> IMPORTED FLAVORED VODKA, 1041200, 1051100, 1062100, 1062200, 1062300, 1071100, 1081300, 1081400, 1081500, 1701100. The whole taxonomy shrank from 100 codes / 96 names in 2016 to 54 codes in 2017. sales.category keeps only the most recent name per code, so every 2016 line is labelled with the post-2016-08-29 name. Codes 1082100, 1091100 and 1092100 additionally have no name at all before 2016-09 (category_name blank on 0.53% of 2016 lines).
- impact: Category-scoped monthly series are not comparable across 2016-08/2016-09: a category can show a fabricated step (e.g. 1031100 jumps from a niche '100 proof vodka' volume to all AMERICAN VODKAS) or a fabricated collapse. Item- and vendor-scoped forecasts are unaffected.
- fix: `min_date` {"date": "2016-09-01"}
- evidence check: **ran** 
```sql
SELECT il.category_code, c.category_name AS current_name, count(*) FILTER (WHERE il.ordered_on < DATE '2016-08-29') AS lines_before, count(*) FILTER (WHERE il.ordered_on >= DATE '2016-08-29') AS lines_after, count(DISTINCT il.item_no) FILTER (WHERE il.ordered_on < DATE '2016-08-29') AS items_before, count(DISTINCT il.item_no) FILTER (WHERE il.ordered_on >= DATE '2016-08-29') AS items_after FROM sales.invoice_line il JOIN sales.category c ON c.category_code = il.category_code WHERE il.category_code IN ('1011300','1011400','1011500','1011600','1012300','1012400','1022100','1031100','1031200','1032200','1041200','1051100','1062100','1062200','1062300','1071100','1081300','1081400','1081500','1701100') GROUP BY 1,2 ORDER BY 1
```
first rows: 1011300, SINGLE BARREL BOURBON WHISKIES, 38887, 56382, 34, 161; 1011400, TENNESSEE WHISKIES, 316, 704732, 8, 140; 1011500, BOTTLED IN BOND BOURBON, 6703, 57391, 27, 80; 1011600, STRAIGHT RYE WHISKIES, 711, 186363, 10, 372; 1012300, SINGLE MALT SCOTCH, 15811, 184773, 91, 458

### category_name_singularised_2025_07: Four category names were re-spelled (plural -> singular) on 2025-07-01
- severity: medium; scope: sales.category, sales.invoice_line [category_name, category_code]; dates: 2025-07-01 to 2026-08-31
- On 2025-07-01 the source renamed, without changing the code: 1081300 AMERICAN CORDIALS & LIQUEURS -> AMERICAN CORDIALS & LIQUEUR, 1082100 IMPORTED CORDIALS & LIQUEURS -> IMPORTED CORDIALS & LIQUEUR, 1091100 AMERICAN DISTILLED SPIRITS SPECIALTY -> AMERICAN DISTILLED SPIRIT SPECIALTY, 1092100 IMPORTED DISTILLED SPIRITS SPECIALTY -> IMPORTED DISTILLED SPIRIT SPECIALTY. This is why the 2025 profile shows 48 category names against only 44 codes. sales.category stores only the latest (singular) name, so grouping by code is safe; grouping by a name string taken from elsewhere, or from any raw/report extract, will split each of these categories into two series at 2025-07.
- impact: A name-keyed category series ends in 2025-06 and a new one starts 2025-07 with the same underlying demand - a false death and a false launch in four cordial/specialty categories.
- fix: `normalize_values` {"column": "category_name", "mapping": {"AMERICAN CORDIALS & LIQUEUR": "AMERICAN CORDIALS & LIQUEURS", "IMPORTED CORDIALS & LIQUEUR": "IMPORTED CORDIALS & LIQUEURS", "AMERICAN DISTILLED SPIRIT SPECIALTY": "AMERICAN DISTILLED SPIRITS SPECIALTY", "IMPORTED DISTILLED SPIRIT SPECIALTY": "IMPORTED DISTILLED SPIRITS SPECIALTY"}}
- evidence check: **ran** 
```sql
SELECT c.category_code, c.category_name, count(*) AS lines, min(il.ordered_on) AS first_line, max(il.ordered_on) AS last_line FROM sales.category c JOIN sales.invoice_line il ON il.category_code = c.category_code WHERE c.category_code IN ('1081300','1082100','1091100','1092100') GROUP BY 1,2 ORDER BY 1
```
first rows: 1081300, AMERICAN CORDIALS & LIQUEUR, 628481, 2016-01-04, 2026-08-31; 1082100, IMPORTED CORDIALS & LIQUEUR, 248665, 2016-01-27, 2026-08-31; 1091100, AMERICAN DISTILLED SPIRIT SPECIALTY, 65743, 2016-01-25, 2026-08-31; 1092100, IMPORTED DISTILLED SPIRIT SPECIALTY, 57071, 2016-02-02, 2026-08-31

### cocktails_rtd_category_discontinued_2022: Category 1071100 COCKTAILS/RTD stops dead on 2022-07-15
- severity: medium; scope: sales.invoice_line, sales.category [category_code, ordered_on]; dates: 2022-07-15 to 2026-08-31
- Code 1071100 (AMERICAN COCKTAILS until 2016-08-26, then COCKTAILS/RTD) carries 416,919 lines and then has no line at all after 2022-07-15. Hypothesis, not verified in this data: ready-to-drink cocktails moved out of the state's Class E wholesale channel (or were re-coded into another category) rather than demand going to zero.
- impact: A forecast for this category, or for any item in it, sees a hard drop to zero in mid-2022 that will be extrapolated as real demand collapse. Total-market series absorb a genuine step down in July 2022 for the same reason.
- fix: `flag_only` {}
- evidence check: **ran** 
```sql
SELECT date_trunc('month', ordered_on)::date AS month, count(*) AS lines, sum(sales_bottles) AS bottles FROM sales.invoice_line WHERE category_code = '1071100' AND ordered_on >= DATE '2021-07-01' GROUP BY 1 ORDER BY 1
```
first rows: 2021-07-01, 7700, 75018; 2021-08-01, 7323, 66122; 2021-09-01, 6018, 49899; 2021-10-01, 5632, 45696; 2021-11-01, 5572, 41308

### zero_value_lines: Zero-dollar / zero-bottle lines: ~1.1k-3.7k per year since 2022, plus zero-dollar lines in 2016-2018
- severity: medium; scope: sales.invoice_line [sales_bottles, sales_dollars]; dates: 2016-01-01 to 2026-08-31
- Lines with sales_dollars <= 0: 526 (2016), 833 (2017), 500 (2018), 0 for 2019-2021, then 1,083 (2022), 3,678 (2023), 2,983 (2024), 2,400 (2025), 1,247 (2026). From 2022 onward the zero-dollar and zero-bottle counts are identical, i.e. the same lines carry both zero quantity and zero value (placeholder / cancelled lines); in 2016-2018 the zero-dollar lines mostly still carry bottles, so they look like free goods or price-less records.
- impact: Harmless for sums but they poison per-line averages, unit price derived as dollars/bottles (division by zero), and line-count-based activity metrics; the 2019-2021 gap means their frequency itself is not a stable series.
- fix: `exclude_zero_lines` {}
- evidence check: **ran** 
```sql
SELECT extract(year FROM ordered_on)::int AS yr, count(*) FILTER (WHERE sales_dollars <= 0) AS zero_dollar_lines, count(*) FILTER (WHERE sales_bottles <= 0) AS zero_bottle_lines, count(*) FILTER (WHERE sales_dollars <= 0 AND sales_bottles <= 0) AS both_zero FROM sales.invoice_line GROUP BY 1 ORDER BY 1
```
first rows: 2016, 526, 6, 1; 2017, 833, 2, 0; 2018, 500, 1, 0; 2019, 0, 0, 0; 2020, 0, 0, 0

### huge_bottle_quantity_lines_2016_2017: 51 lines with implausibly large sales_bottles, confined to 2016-2017
- severity: medium; scope: sales.invoice_line [sales_bottles, sales_dollars, sales_liters]; dates: 2016-01-01 to 2017-12-31
- Profiling flags 27 'huge bottles' lines in 2016 and 24 in 2017, and none in any later year. These are single order lines whose bottle count is orders of magnitude above the line distribution - most likely keying errors or case/bottle unit confusion in the early source files.
- impact: A handful of lines can dominate a monthly total for a single item, store or small county, creating a one-month spike that a seasonal model will try to repeat every year.
- fix: `cap_outliers` {"k": 5}
- evidence check: **ran** 
```sql
SELECT date_trunc('month', ordered_on)::date AS month, count(*) AS huge_lines, max(sales_bottles) AS max_bottles, sum(sales_bottles) AS bottles FROM sales.invoice_line WHERE sales_bottles > 20000 GROUP BY 1 ORDER BY 1 LIMIT 50
```
first rows: 

### implausible_bottle_volumes: Impossible bottle_volume_ml values (up to 378,000 ml) distort liters
- severity: low; scope: sales.invoice_line, sales.item [bottle_volume_ml, sales_liters]; dates: 2016-01-01 to 2026-08-31
- The bottle-size distribution contains values that cannot be single bottles: 31,500 ml (24 lines), 189,000 ml (2 lines), 225,000 ml (1 line), 378,000 ml (24 lines), plus a long tail of case-like sizes (4,500 / 5,250 / 6,000 / 9,000 ml, ~2,700 lines) and sub-100 ml oddities (20, 25 ml). sales_liters is derived from bottle volume in the source, so these lines contribute wildly inflated liters for a normal bottle count.
- impact: Only affects sales_liters targets (and liters-per-bottle features); a single 378,000 ml line adds hundreds of thousands of liters to a month. sales_bottles and sales_dollars are unaffected.
- fix: `cap_outliers` {"k": 5}
- evidence check: **ran** 
```sql
SELECT bottle_volume_ml, count(*) AS lines, sum(sales_bottles) AS bottles, round(sum(sales_liters), 1) AS liters FROM sales.invoice_line WHERE bottle_volume_ml >= 4500 OR bottle_volume_ml <= 25 GROUP BY 1 ORDER BY 1
```
first rows: 20, 3070, 21321, 418.2; 25, 2409, 8324, 178.1; 4500, 782, 1000, 4481.0; 4800, 25, 25, 120.0; 5250, 725, 1384, 7266.0

### dimension_tables_hold_latest_attributes_only: item/store/vendor/category dimensions are as-of-today, not as-of-order-date
- severity: medium; scope: sales.item, sales.store, sales.category, sales.invoice_line [category_code, pack, bottle_volume_ml, city, county_fips, county_name, store_name]; dates: 2016-01-01 to 2026-08-31
- The loader keeps each code's most recently recorded attributes in sales.item, sales.store, sales.vendor and sales.category, while sales.invoice_line keeps pack, bottle_volume_ml and category_code as recorded on the order date. Grouping by sales.item.category_code therefore back-fills today's taxonomy over all history, whereas grouping by sales.invoice_line.category_code uses the contemporaneous one - the two give different monthly series. Store drift is real: of 3,199 stores, 462 changed name, 272 changed address, 22 changed city and 17 changed county over the window.
- impact: Region and category scopes can shift retroactively: a store that moved county has all of its 2016-2026 history assigned to its latest county, so a county series gains or loses a store's entire past. Pick one convention per request and state it; prefer sales.invoice_line.category_code for category scopes.
- fix: `flag_only` {}
- evidence check: **ran** 
```sql
SELECT extract(year FROM il.ordered_on)::int AS yr, count(*) AS lines, count(*) FILTER (WHERE il.category_code IS DISTINCT FROM i.category_code) AS category_mismatch, count(*) FILTER (WHERE il.bottle_volume_ml IS DISTINCT FROM i.bottle_volume_ml) AS volume_mismatch, count(*) FILTER (WHERE il.pack IS DISTINCT FROM i.pack) AS pack_mismatch FROM sales.invoice_line il JOIN sales.item i ON i.item_no = il.item_no GROUP BY 1 ORDER BY 1
```
first rows: 2016, 2279893, 838986, 154605, 30229; 2017, 2291276, 164237, 178659, 35936; 2018, 2355558, 182318, 198060, 41393; 2019, 2380345, 169681, 124997, 42401; 2020, 2614365, 211406, 4223, 37690

### missing_county_attribution: Stores without a county: 18 stores, ~$326k of sales, and 4.3% of 2016 lines had no county name
- severity: medium; scope: sales.store, sales.invoice_line [county_fips, county_name]; dates: 2016-01-01 to 2026-08-31
- 18 of 3,199 stores have no county_fips; their sales (~$325,569 in the county roll-up, shown as a NULL county row) fall out of every county-level aggregate. County name blanks were much more common early: 4.31% of 2016 lines, 1.90% of 2017, 0.086% of 2018, and effectively 0 from 2021 onward. Store address is similarly blank on 1.31% of 2016 and 1.90% of 2017 lines.
- impact: Statewide totals do not equal the sum of county totals, and county-level series for 2016-2017 are under-counted relative to later years, producing a spurious upward trend in county coverage.
- fix: `flag_only` {}
- evidence check: **ran** 
```sql
SELECT extract(year FROM il.ordered_on)::int AS yr, count(*) AS lines, count(*) FILTER (WHERE s.county_fips IS NULL) AS lines_no_county, round(sum(il.sales_dollars) FILTER (WHERE s.county_fips IS NULL), 2) AS dollars_no_county FROM sales.invoice_line il LEFT JOIN sales.store s ON s.store_no = il.store_no GROUP BY 1 ORDER BY 1
```
first rows: 2016, 2279893, 9368, 799384.11; 2017, 2291276, 3805, 319385.74; 2018, 2355558, 3133, 275636.66; 2019, 2380345, 3080, 419502.01; 2020, 2614365, 2044, 481021.69

### reference_data_lag: County population ends 2025 and county income ends 2024, but sales run to 2026-08
- severity: medium; scope: ref.county_population, ref.county_income, sales.invoice_line [year, population, median_household_income]; dates: 2025-01-01 to 2026-08-31
- ref.county_population covers 2016-2025 and ref.county_income covers 2016-2024, while sales.invoice_line covers 2016-01-04 to 2026-08-31. Census SAIPE and population estimates are published with a 1-2 year lag, so the most recent periods will never have a matching reference row at forecast time.
- impact: An inner join to a per-capita or income covariate silently truncates 2025 (income) and 2026 (both) from the training/scoring frame, or produces NULL per-capita rates for the most recent and most relevant months.
- fix: `carry_forward_reference` {}
- evidence check: **ran** 
```sql
SELECT (SELECT max(year) FROM ref.county_population) AS pop_max_year, (SELECT min(year) FROM ref.county_population) AS pop_min_year, (SELECT max(year) FROM ref.county_income) AS income_max_year, (SELECT min(year) FROM ref.county_income) AS income_min_year, (SELECT max(ordered_on) FROM sales.invoice_line) AS last_order, (SELECT min(ordered_on) FROM sales.invoice_line) AS first_order
```
first rows: 2025, 2016, 2024, 2016, 2026-08-31, 2016-01-04

### partial_trailing_month: Series end mid-window: 2026 is a partial year and the last month may be incomplete
- severity: high; scope: sales.invoice_line [ordered_on]; dates: 2026-08-01 to 2026-08-31
- Coverage runs to 2026-08-31; 2026 has only 8 months (19.47M bottles vs 30.44M for full-year 2025), so any year-over-year comparison of 2026 against earlier years is meaningless. The final loaded month is also at risk of being partially reported (late-arriving orders), which cannot be verified from inside the warehouse.
- impact: A partial trailing month reads as a sharp demand drop and drags the level/trend of any recursive forecast; annual aggregates for 2026 are ~2/3 of a year.
- fix: `flag_only` {}
- evidence check: **ran** 
```sql
SELECT date_trunc('month', ordered_on)::date AS month, count(*) AS lines, sum(sales_bottles) AS bottles, max(ordered_on) AS last_day FROM sales.invoice_line WHERE ordered_on >= DATE '2025-09-01' GROUP BY 1 ORDER BY 1
```
first rows: 2025-09-01, 206158, 2550832, 2025-09-30; 2025-10-01, 214815, 2778821, 2025-10-31; 2025-11-01, 195311, 2427078, 2025-11-30; 2025-12-01, 246511, 2849076, 2025-12-31; 2026-01-01, 182995, 2163052, 2026-01-30

### store_entry_exit_and_left_censoring: Store panel is unbalanced: 1,254 stores 'open' in 2016-01 by construction, 10-28 new stores every month
- severity: medium; scope: sales.store, sales.invoice_line [first_order_on, last_order_on, store_no]; dates: 2016-01-01 to 2026-08-31
- first_order_on is left-censored: 1,254 stores show their first order in 2016-01 simply because the data starts 2016-01-04. Thereafter 5-55 stores open every month (e.g. 28 in 2025-10, 20 in 2026-08), and the licensed-store base grows steadily across the window. Stores also stop ordering (closures/licence lapses) - last_order_on well before 2026-08 marks a dead series, not zero demand.
- impact: Statewide, county and city totals contain a composition trend from store entry that is not per-store demand growth. Store-level forecasts started before first_order_on, or continued past last_order_on, will show fake zeros at both ends.
- fix: `flag_only` {}
- evidence check: **ran** 
```sql
SELECT count(*) AS stores, count(*) FILTER (WHERE first_order_on < DATE '2016-02-01') AS censored_openers, count(*) FILTER (WHERE last_order_on < DATE '2026-03-01') AS inactive_6m_plus, count(*) FILTER (WHERE last_order_on < DATE '2025-09-01') AS inactive_12m_plus, count(*) FILTER (WHERE first_order_on >= DATE '2025-09-01') AS opened_last_12m FROM sales.store
```
first rows: 3199, 1254, 1022, 927, 193

### covid_2020_level_shift: 2020 demand step (+11% bottles over 2019) persists into 2021
- severity: medium; scope: sales.invoice_line [sales_bottles, sales_dollars, ordered_on]; dates: 2020-03-01 to 2021-12-31
- Annual bottles move 22.67M (2016), 23.99M, 25.44M, 26.84M (2019), then 29.84M in 2020 (+11.2%) and 31.20M in 2021, versus a ~4-6%/yr trend before. Attribution to the 2020 pandemic shift from on-premise to off-premise consumption is a hypothesis; the warehouse contains no channel flag to confirm it. 2022 then dips to 30.43M.
- impact: A one-off level shift in 2020 inflates trend estimates fitted across 2019-2021 and distorts any seasonality learned from 2020's March-April period. Consider a level-shift/intervention term rather than deleting the period.
- fix: `flag_only` {}
- evidence check: **ran** 
```sql
SELECT date_trunc('month', ordered_on)::date AS month, sum(sales_bottles) AS bottles, round(sum(sales_dollars), 0) AS dollars FROM sales.invoice_line WHERE ordered_on >= DATE '2019-07-01' AND ordered_on < DATE '2021-07-01' GROUP BY 1 ORDER BY 1
```
first rows: 2019-07-01, 2400744, 30967400; 2019-08-01, 2243518, 28424263; 2019-09-01, 2123913, 28078111; 2019-10-01, 2571873, 34448213; 2019-11-01, 2288303, 30270165


## request_specific

### city_spelling_variants: City spelled two ways: MOUNT PLEASANT / MT PLEASANT and SAINT ANSGAR / ST ANSGAR
- severity: low; scope: sales.store [city]; dates: 2016-01-01 to 2026-08-31
- City-scoped requests only. MOUNT PLEASANT (11 stores, 82,152 lines) coexists with MT PLEASANT (2 stores, 25,318 lines); SAINT ANSGAR (2 stores, 2,365 lines) with ST ANSGAR (2 stores, 11,029 lines). Other MOUNT*/ST* cities (FORT DODGE, MOUNT VERNON, ST CHARLES, ST LUCAS, ...) have no competing spelling.
- impact: A city filter on one spelling silently drops 24-82% of that city's volume.
- fix: `normalize_values` {"column": "city", "mapping": {"MT PLEASANT": "MOUNT PLEASANT", "ST ANSGAR": "SAINT ANSGAR"}}
- evidence check: **ran** 
```sql
SELECT s.city, count(DISTINCT s.store_no) AS stores, count(*) AS lines FROM sales.store s JOIN sales.invoice_line il ON il.store_no = s.store_no WHERE s.city IN ('MOUNT PLEASANT','MT PLEASANT','SAINT ANSGAR','ST ANSGAR') GROUP BY 1 ORDER BY 1
```
first rows: MOUNT PLEASANT, 11, 77721; MT PLEASANT, 2, 23752; SAINT ANSGAR, 2, 2220; ST ANSGAR, 2, 10980

### item_renumbering_titos_mini: Item renumbered: TITOS HANDMADE VODKA MINI 50ml 38180 -> 38194 in July 2020
- severity: low; scope: sales.invoice_line, sales.item [item_no]; dates: 2020-07-27 to 2020-07-31
- Item-scoped requests only. 38180 (TITOS HANDMADE VODKA MINI, 50 ml) runs 2016-01-04 to 2020-07-27 (13,033 lines); 38194, same description and volume, starts 2020-07-31 and runs to 2026-08-31 with 53,974 lines and 6x the bottles. A stray 938180 (same description, 50 ml, 96 lines) exists only 2020-07-10..2020-08-20, overlapping the switch. Separately, 100 ml TITOS appears as 38449 (2025-11-10..2026-06-03) and 102747 (from 2026-05-18) - a probable second renumbering with a one-month overlap.
- impact: Forecasting 38180 sees a discontinued item; forecasting 38194 sees a 2020 launch with no history. Both are wrong unless the series are stitched.
- fix: `stitch_successor` {"column": "item_no", "from": "38180", "to": "38194"}
- evidence check: **ran** 
```sql
SELECT il.item_no, i.item_desc, i.bottle_volume_ml, count(*) AS lines, sum(il.sales_bottles) AS bottles, min(il.ordered_on) AS first_order, max(il.ordered_on) AS last_order FROM sales.invoice_line il JOIN sales.item i ON i.item_no = il.item_no WHERE i.item_desc LIKE 'TITOS%' GROUP BY 1,2,3 ORDER BY bottles DESC LIMIT 20
```
first rows: 38177, TITOS HANDMADE VODKA, 1000, 100148, 4038062, 2016-01-04, 2026-08-31; 38176, TITOS HANDMADE VODKA, 750, 198394, 3658750, 2016-01-04, 2026-08-31; 38178, TITOS HANDMADE VODKA, 1750, 166317, 3195495, 2016-01-04, 2026-08-31; 38174, TITOS HANDMADE VODKA, 375, 118811, 1326720, 2016-01-15, 2026-08-31; 38179, TITOS HANDMADE VODKA, 200, 31871, 535145, 2017-02-17, 2026-08-31
