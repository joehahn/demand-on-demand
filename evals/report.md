# Agent eval report

19 cases, 38 runs, model `claude-sonnet-5`, 2026-09-26 17:47.

- Runs fully correct: **38/38** (100%)
- Cases correct on every run: **19/19**
- Cost: $2.33 total, $0.061 per run; median 40s and 7 tool calls per run

| tag | runs correct |
|---|---|
| breakout | 2/2 |
| dev | 10/10 |
| fresh | 28/28 |
| held_out | 10/10 |
| recode | 2/2 |
| refusal | 4/4 |
| register | 4/4 |
| renumbering | 4/4 |
| resolution | 18/18 |
| restraint | 2/2 |
| spelling | 4/4 |
| target | 4/4 |
| vague | 4/4 |
| vendor | 2/2 |

| case | runs correct | failures |
|---|---|---|
| titos_polk | 2/2 |  |
| titos_minis_by_item | 2/2 |  |
| titos_minis_des_moines | 2/2 |  |
| crown_mount_pleasant | 2/2 |  |
| tennessee_whiskey | 2/2 |  |
| vodka_top_counties | 2/2 |  |
| chicago | 2/2 |  |
| horizon_24 | 2/2 |  |
| jack_iowa_city | 2/2 |  |
| fireball_linn_revenue | 2/2 |  |
| statewide_liters | 2/2 |  |
| diageo_scott | 2/2 |  |
| titos_st_ansgar | 2/2 |  |
| bottled_in_bond | 2/2 |  |
| titos_100_by_item | 2/2 |  |
| rtd_cocktails_recode | 2/2 |  |
| hawkeye_johnson | 2/2 |  |
| ames_whiskey | 2/2 |  |
| vague_vodka | 2/2 |  |

Re-run after adding the register-proposal check (5 cases x 2 runs): 10/10 correct; the Cocktails/RTD runs each filed a correct register proposal and no other case filed one.
