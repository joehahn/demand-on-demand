# Onboarding decisions, 2026-09-26

Claude (`claude-opus-5`) drafted 17 issues from the warehouse profile (`review.md`). Every evidence
query was re-run under the read-only agent role. A human (Joe Hahn) then decided:

**Approved into `meta.known_issues` (12):** raw_export_duplicate_rows, invoice_id_semantics_change_2025_09,
bottle_price_columns_null_before_2025, category_code_reassignment_aug_2016,
cocktails_rtd_category_discontinued_2022, zero_value_lines, implausible_bottle_volumes,
dimension_tables_hold_latest_attributes_only, missing_county_attribution, reference_data_lag,
partial_trailing_month, store_entry_exit_and_left_censoring.

**Rejected (3):**
- `huge_bottle_quantity_lines_2016_2017`: misread of the profile (the 51 "huge" lines are large bottle
  *sizes*, already covered by implausible_bottle_volumes). Claude's own evidence query returned 0 rows,
  which is how the verification step caught it.
- `covid_2020_level_shift`: real demand, not a data defect; the forecaster should learn it, not fix it.
- `category_name_singularised_2025_07`: accurate, but the renaming exists only in raw data; the agent
  groups by code, so it has no effect on forecasts.

**Held out by design (2 request-specific):** `item_renumbering_titos_mini`, `city_spelling_variants`.
Not in the register, so the forecasting agent must find them itself; they are eval cases.

Cost: about $0.51 per drafting run (a first run was lost to a script bug, so about $1.02 in total).
