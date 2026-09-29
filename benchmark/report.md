# Forecast-accuracy benchmark

30 forecasts sampled from the warehouse (seed 0), 30 completed, in 521s (17s median each).

- Beat "same month last year" on the 24-month test window: **23 of 30** (77%)
- Median error relative to that baseline: **0.88** (below 1 is better)
- Median monthly error (WAPE): model 15.0%, baseline 16.0%

| forecast | horizon | relative error | model error | baseline error | model |
|---|---|---|---|---|---|
| American Brandies, Iowa, dollars, 12 months | 12 | 0.46 | 4.4% | 9.6% | ridge |
| American Schnapps, Iowa, bottles, 3 months | 3 | 0.55 | 4.7% | 8.6% | lightgbm |
| American Vodkas, Iowa, bottles, 12 months | 12 | 0.71 | 2.9% | 4.1% | ridge |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 12 | 0.73 | 15.0% | 20.5% | ridge |
| Flavored Rum, Iowa, liters, 3 months | 3 | 0.80 | 9.4% | 11.7% | ridge |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 12 | 0.81 | 71.7% | 89.6% | ridge |
| Imported Brandies, Woodbury County, dollars, 3 months | 3 | 0.81 | 18.9% | 23.3% | ridge |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 6 | 0.82 | 4.1% | 5.0% | ridge |
| American Flavored Vodka, Fayette County, dollars, 12 months | 12 | 0.84 | 20.5% | 24.7% | ridge |
| Luxco Inc, Lee County, dollars, 6 months | 6 | 0.84 | 22.1% | 26.3% | ridge |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 6 | 0.85 | 13.6% | 16.1% | ridge |
| American Brandies, Marshall County, dollars, 6 months | 6 | 0.85 | 20.0% | 23.5% | lightgbm |
| Imported Vodkas, Iowa, liters, 6 months | 6 | 0.86 | 15.5% | 18.0% | ridge |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 12 | 0.86 | 8.2% | 9.5% | ridge |
| Proximo, O'Brien County, liters, 6 months | 6 | 0.88 | 25.8% | 29.4% | lightgbm |
| Jim Beam Brands, Johnson County, bottles, 12 months | 12 | 0.88 | 11.8% | 13.5% | ridge |
| Black Velvet 200 ml, Boone County, liters, 6 months | 6 | 0.94 | 66.3% | 70.8% | ridge |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 3 | 0.95 | 13.9% | 14.7% | ridge |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 6 | 0.95 | 23.0% | 24.3% | lightgbm |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 6 | 0.96 | 15.0% | 15.6% | ridge |
| All liquor, statewide | 6 | 0.97 | 4.7% | 4.9% | ridge |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 12 | 0.99 | 49.6% | 49.8% | lightgbm |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 6 | 1.00 | 99.9% | 98.7% | lightgbm |
| Luxco Inc, Dickinson County, dollars, 12 months | 12 | 1.04 | 17.3% | 16.7% | ridge |
| Diageo Americas, Warren County, liters, 6 months | 6 | 1.07 | 13.7% | 12.9% | ridge |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 12 | 1.13 | 20.7% | 18.2% | lightgbm |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 12 | 1.14 | 12.7% | 11.1% | ridge |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 12 | 1.23 | 19.5% | 15.8% | lightgbm |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 12 | 1.43 | 8.8% | 6.2% | ridge |
| Irish Whiskies, Iowa, bottles, 12 months | 12 | 1.54 | 9.5% | 6.2% | lightgbm |
