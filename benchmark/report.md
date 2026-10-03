# Forecast-accuracy benchmark

30 forecasts sampled from the warehouse (seed 0), 30 completed, in 237s (9s median each).

- Beat "same month last year" on the 24-month test window: **20 of 30** (67%)
- Median error relative to that baseline: **0.91** (below 1 is better)
- Median monthly error (WAPE): model 16.2%, baseline 16.0%

| forecast | horizon | relative error | model error | baseline error | model |
|---|---|---|---|---|---|
| American Brandies, Iowa, dollars, 12 months | 12 | 0.41 | 4.0% | 9.6% | ridge |
| American Schnapps, Iowa, bottles, 3 months | 3 | 0.65 | 5.6% | 8.6% | ridge |
| American Vodkas, Iowa, bottles, 12 months | 12 | 0.71 | 2.9% | 4.1% | ridge |
| Imported Brandies, Woodbury County, dollars, 3 months | 3 | 0.78 | 18.0% | 23.3% | ridge |
| Flavored Rum, Iowa, liters, 3 months | 3 | 0.78 | 9.1% | 11.7% | ridge |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 12 | 0.81 | 7.7% | 9.5% | ridge |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 6 | 0.85 | 13.6% | 16.1% | ridge |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 12 | 0.87 | 9.7% | 11.1% | ridge |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 6 | 0.88 | 4.4% | 5.0% | ridge |
| Jim Beam Brands, Johnson County, bottles, 12 months | 12 | 0.88 | 11.8% | 13.5% | ridge |
| Luxco Inc, Lee County, dollars, 6 months | 6 | 0.89 | 23.4% | 26.3% | ridge |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 12 | 0.89 | 79.0% | 89.6% | ridge |
| American Brandies, Marshall County, dollars, 6 months | 6 | 0.89 | 20.9% | 23.5% | ridge |
| Imported Vodkas, Iowa, liters, 6 months | 6 | 0.90 | 16.2% | 18.0% | ridge |
| All liquor, statewide | 6 | 0.90 | 4.4% | 4.9% | ridge |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 6 | 0.92 | 22.2% | 24.3% | ridge |
| Black Velvet 200 ml, Boone County, liters, 6 months | 6 | 0.94 | 66.3% | 70.8% | ridge |
| Proximo, O'Brien County, liters, 6 months | 6 | 0.96 | 28.2% | 29.4% | lightgbm |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 12 | 0.98 | 17.9% | 18.2% | ridge |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 6 | 1.00 | 99.9% | 98.7% | lightgbm |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 12 | 1.02 | 20.9% | 20.5% | ridge |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 6 | 1.04 | 16.2% | 15.6% | ridge |
| Luxco Inc, Dickinson County, dollars, 12 months | 12 | 1.04 | 17.3% | 16.7% | ridge |
| Diageo Americas, Warren County, liters, 6 months | 6 | 1.04 | 13.3% | 12.9% | ridge |
| American Flavored Vodka, Fayette County, dollars, 12 months | 12 | 1.06 | 26.0% | 24.7% | ridge |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 3 | 1.09 | 16.1% | 14.7% | ridge |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 12 | 1.14 | 18.0% | 15.8% | ridge |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 12 | 1.33 | 66.7% | 49.8% | ridge |
| Irish Whiskies, Iowa, bottles, 12 months | 12 | 1.42 | 8.7% | 6.2% | ridge |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 12 | 1.50 | 9.2% | 6.2% | ridge |
