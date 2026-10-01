# Experiment: a finer hyperparameter grid

Ridge regularization 0.1, 0.3, 1, 3, 10, 30 and LightGBM 4, 7, 11, 15, 23, 31 leaves (288 configurations) against the
current 1 or 10 and 7 or 15 leaves (96), on the benchmark's 30 forecasts. Error relative to same month last year
on the 24-month test window (below 1 beats it).

- Beat last year: current **23 of 30**, finer **20 of 30**
- Median relative error: current **0.880**, finer **0.931**
- Finer grid better on 18, worse on 11
- Median harness time: current 17 s, finer 36 s

| forecast | current | finer | current s | finer s |
|---|---|---|---|---|
| All liquor, statewide | 0.969 | 0.968 | 24 | 41 |
| Imported Brandies, Woodbury County, dollars, 3 months | 0.813 | 0.923 | 17 | 36 |
| American Brandies, Marshall County, dollars, 6 months | 0.848 | 0.828 | 20 | 38 |
| Jim Beam Brands, Johnson County, bottles, 12 months | 0.882 | 0.843 | 14 | 26 |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 0.861 | 0.861 | 8 | 21 |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 1.133 | 1.099 | 12 | 28 |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 1.428 | 1.170 | 15 | 31 |
| American Brandies, Iowa, dollars, 12 months | 0.456 | 0.451 | 14 | 30 |
| American Flavored Vodka, Fayette County, dollars, 12 months | 0.835 | 1.071 | 11 | 26 |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 0.958 | 1.030 | 14 | 36 |
| American Vodkas, Iowa, bottles, 12 months | 0.707 | 0.717 | 17 | 32 |
| Black Velvet 200 ml, Boone County, liters, 6 months | 0.938 | 0.938 | 18 | 38 |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 0.998 | 0.963 | 11 | 31 |
| Irish Whiskies, Iowa, bottles, 12 months | 1.545 | 1.145 | 18 | 38 |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 0.989 | 1.429 | 25 | 38 |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 0.846 | 0.791 | 11 | 31 |
| Imported Vodkas, Iowa, liters, 6 months | 0.859 | 0.859 | 19 | 44 |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 0.731 | 0.734 | 17 | 33 |
| Flavored Rum, Iowa, liters, 3 months | 0.805 | 0.861 | 21 | 49 |
| Diageo Americas, Warren County, liters, 6 months | 1.070 | 1.055 | 19 | 43 |
| Luxco Inc, Lee County, dollars, 6 months | 0.838 | 0.879 | 19 | 43 |
| American Schnapps, Iowa, bottles, 3 months | 0.552 | 0.603 | 24 | 52 |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 1.441 | 1.345 | 16 | 30 |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 0.812 | 0.812 | 10 | 25 |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 0.945 | 0.945 | 27 | 51 |
| Proximo, O'Brien County, liters, 6 months | 0.877 | 0.863 | 16 | 40 |
| Luxco Inc, Dickinson County, dollars, 12 months | 1.037 | 1.012 | 13 | 31 |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 1.143 | 1.241 | 16 | 33 |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 0.949 | 0.914 | 21 | 47 |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 0.825 | 1.000 | 20 | 45 |

Conclusion (2026-09-30): not adopted. The finer grid wins small on 18 forecasts but loses big on several (e.g. 0.99 ->
1.43, 0.84 -> 1.07), beats last year less often (20 vs 23 of 30), has a worse median (0.931 vs 0.880), and takes about
twice as long: with 288 candidates scored on ~20 forecasts each, model selection more often picks a configuration that
was lucky there. The averaging of the top configurations and the blend with last year already smooth over exact sizes.
