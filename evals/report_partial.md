# Agent eval report

5 cases, 10 runs, model `claude-sonnet-5`, 2026-09-26 17:47.

- Runs fully correct: **10/10** (100%)
- Cases correct on every run: **5/5**
- Cost: $0.99 total, $0.099 per run; median 58s and 7 tool calls per run

| tag | runs correct |
|---|---|
| dev | 4/4 |
| fresh | 6/6 |
| held_out | 8/8 |
| recode | 2/2 |
| renumbering | 4/4 |
| resolution | 2/2 |
| spelling | 2/2 |

| case | runs correct | failures |
|---|---|---|
| titos_polk | 2/2 |  |
| titos_minis_by_item | 2/2 |  |
| crown_mount_pleasant | 2/2 |  |
| titos_100_by_item | 2/2 |  |
| rtd_cocktails_recode | 2/2 |  |
