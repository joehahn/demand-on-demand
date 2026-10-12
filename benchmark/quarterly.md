# Experiment: quarterly forecasts, bottom-up from months vs modelled on quarters

Error relative to the same quarter last year on the Testing period, over forecasts made at quarter starts for the next 4 quarters (below 1 beats it). A = bottom-up (monthly models, quarters are sums of months, as today); B = direct (models learn from quarterly sums).

**30 forecasts**

| arm | beat last year | median | mean |
|---|---|---|---|
| A | 13 | 1.074 | 1.100 |
| B | 15 | 0.991 | 1.087 |

B vs A: better on 14, worse on 16.

| forecast | A bottom-up | B direct | quarters scored |
|---|---|---|---|
| All liquor, statewide | 0.649 | 1.585 | 16 |
| Imported Brandies, Woodbury County, dollars, 3 months | 1.299 | 1.371 | 16 |
| American Brandies, Marshall County, dollars, 6 months | 0.834 | 0.804 | 16 |
| Jim Beam Brands, Johnson County, bottles, 12 months | 0.662 | 0.565 | 16 |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 0.493 | 0.583 | 16 |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 0.928 | 1.350 | 16 |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 1.502 | 1.906 | 16 |
| American Brandies, Iowa, dollars, 12 months | 0.272 | 0.413 | 16 |
| American Flavored Vodka, Fayette County, dollars, 12 months | 1.493 | 1.711 | 16 |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 0.965 | 1.363 | 16 |
| American Vodkas, Iowa, bottles, 12 months | 0.792 | 0.957 | 16 |
| Black Velvet 200 ml, Boone County, liters, 6 months | 0.569 | 0.588 | 16 |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 1.089 | 1.915 | 16 |
| Irish Whiskies, Iowa, bottles, 12 months | 1.726 | 1.163 | 16 |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 0.958 | 1.000 | 16 |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 0.704 | 0.724 | 16 |
| Imported Vodkas, Iowa, liters, 6 months | 1.060 | 1.218 | 16 |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 1.126 | 0.982 | 16 |
| Flavored Rum, Iowa, liters, 3 months | 1.096 | 0.974 | 16 |
| Diageo Americas, Warren County, liters, 6 months | 1.395 | 1.344 | 16 |
| Luxco Inc, Lee County, dollars, 6 months | 0.781 | 0.886 | 16 |
| American Schnapps, Iowa, bottles, 3 months | 1.458 | 0.895 | 16 |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 2.710 | 1.728 | 16 |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 1.045 | 0.958 | 16 |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 1.365 | 0.632 | 16 |
| Proximo, O'Brien County, liters, 6 months | 0.920 | 0.625 | 16 |
| Luxco Inc, Dickinson County, dollars, 12 months | 1.087 | 1.269 | 16 |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 1.286 | 0.743 | 16 |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 1.093 | 1.069 | 16 |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 1.639 | 1.274 | 16 |
