# Experiment: forecast big buyers separately (2026-09-30)

For each single-series forecast in the benchmark sample plus the five examples, stores with more than 20% of the
series during model selection (before the test window) were split out. The harness forecast the rest; the big
buyers got their expected volume from earlier data only (same calendar month in up to 3 prior years, or the last
12 months' average). Scored like the harness: error relative to same month last year on the same test months.

34 single-series forecasts, 12 with a big buyer.

- Same calendar month: better than the current method on 2 of 12; median 0.944 -> 1.065
- 12-month average: better on 4 of 12; median 0.944 -> 0.974

Conclusion: not adopted. Most big buyers' timing is too irregular; pooling and the blend with last year already
absorb them better. Dashboards name a big buyer (over 25% of the last 12 months) instead.

| forecast | big buyers | their share | current | split, same month | split, 12-month average |
|---|---|---|---|---|---|
| American Brandies, Marshall County, dollars, 6 months | 2 | 51% | 0.848 | 1.065 | 0.952 |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 1 | 26% | 0.958 | 1.058 | 0.999 |
| Black Velvet 200 ml, Boone County, liters, 6 months | 2 | 80% | 0.938 | 1.065 | 0.996 |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 2 | 51% | 0.998 | 0.966 | 0.821 |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 2 | 55% | 0.989 | 1.177 | 1.124 |
| Diageo Americas, Warren County, liters, 6 months | 1 | 30% | 1.070 | 1.092 | 1.320 |
| Luxco Inc, Lee County, dollars, 6 months | 1 | 28% | 0.838 | 0.984 | 0.717 |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 1 | 23% | 0.812 | 0.821 | 0.821 |
| Proximo, O'Brien County, liters, 6 months | 1 | 48% | 0.877 | 1.111 | 0.852 |
| Luxco Inc, Dickinson County, dollars, 12 months | 2 | 49% | 1.037 | 1.439 | 2.015 |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 1 | 34% | 0.949 | 1.154 | 0.873 |
| Tito's minis, Des Moines, next 5 months | 1 | 29% | 0.920 | 0.864 | 1.049 |
