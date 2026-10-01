# Experiment: a middle hyperparameter grid

Ridge regularization 0.1, 1, 5, 10 and LightGBM 3, 7, 12, 17 leaves, against the current 1 or 10 and 7 or 15 leaves, on the
benchmark's 30 forecasts. Error relative to same month last year on the 24-month test window (below 1 beats it).

- Beat last year: current **23 of 30**, middle **20 of 30**
- Median relative error: current **0.880**, middle **0.920**
- Middle grid better on 13, worse on 11
- Median harness time: current 17 s, middle 24 s

| forecast | current | middle | current s | middle s |
|---|---|---|---|---|
| All liquor, statewide | 0.969 | 0.968 | 24 | 32 |
| Imported Brandies, Woodbury County, dollars, 3 months | 0.813 | 0.919 | 17 | 25 |
| American Brandies, Marshall County, dollars, 6 months | 0.848 | 0.843 | 20 | 25 |
| Jim Beam Brands, Johnson County, bottles, 12 months | 0.882 | 1.023 | 14 | 18 |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 0.861 | 0.861 | 8 | 12 |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 1.133 | 1.090 | 12 | 18 |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 1.428 | 1.252 | 15 | 21 |
| American Brandies, Iowa, dollars, 12 months | 0.456 | 0.456 | 14 | 20 |
| American Flavored Vodka, Fayette County, dollars, 12 months | 0.835 | 0.835 | 11 | 18 |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 0.958 | 1.034 | 14 | 24 |
| American Vodkas, Iowa, bottles, 12 months | 0.707 | 0.717 | 17 | 24 |
| Black Velvet 200 ml, Boone County, liters, 6 months | 0.938 | 0.938 | 18 | 26 |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 0.998 | 0.994 | 11 | 21 |
| Irish Whiskies, Iowa, bottles, 12 months | 1.545 | 1.531 | 18 | 23 |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 0.989 | 1.136 | 25 | 30 |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 0.846 | 0.846 | 11 | 20 |
| Imported Vodkas, Iowa, liters, 6 months | 0.859 | 0.859 | 19 | 28 |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 0.731 | 0.752 | 17 | 22 |
| Flavored Rum, Iowa, liters, 3 months | 0.805 | 0.902 | 21 | 34 |
| Diageo Americas, Warren County, liters, 6 months | 1.070 | 1.057 | 19 | 31 |
| Luxco Inc, Lee County, dollars, 6 months | 0.838 | 0.879 | 19 | 30 |
| American Schnapps, Iowa, bottles, 3 months | 0.552 | 0.568 | 24 | 35 |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 1.441 | 1.243 | 16 | 22 |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 0.812 | 0.812 | 10 | 17 |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 0.945 | 0.945 | 27 | 37 |
| Proximo, O'Brien County, liters, 6 months | 0.877 | 0.841 | 16 | 25 |
| Luxco Inc, Dickinson County, dollars, 12 months | 1.037 | 1.020 | 13 | 19 |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 1.143 | 1.234 | 16 | 22 |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 0.949 | 0.921 | 21 | 29 |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 0.825 | 0.825 | 20 | 31 |

Conclusion (2026-09-30): not adopted. Like the finer grid, it helps more forecasts than it hurts (13 vs 11) but the
losses are larger, it beats last year less often (20 vs 23 of 30), has a worse median (0.920 vs 0.880), and is about
40% slower. The coarse grid acts as useful restraint when selection is scored on ~20 forecasts per configuration.
