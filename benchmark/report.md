# Forecast-accuracy benchmark

30 forecasts sampled from the warehouse (seed 0), 30 completed, in 296s (6s median each).

- Beat "same month last year" on the 24-month test window: **18 of 30** (60%)
- Median error relative to that baseline: **0.92** (below 1 is better)
- Median monthly error (WAPE, weighted absolute percentage error: total absolute error divided by total actual sales): model 15.4%, baseline 16.0%
- Volume matters: the 10 forecasts with the fewest sales records per month beat the baseline 3 times, the 10 with the most 9 times. With a handful of orders a month, one order more or less swings the total, and neither the model nor the baseline can predict that.

| forecast | horizon | sales records per month | relative error | model error | baseline error | model |
|---|---|---|---|---|---|---|
| American Brandies, Iowa, dollars, 12 months | 12 | 5,632 | 0.45 | 4.3% | 9.6% | ridge |
| American Schnapps, Iowa, bottles, 3 months | 3 | 7,114 | 0.54 | 4.7% | 8.6% | lightgbm |
| American Vodkas, Iowa, bottles, 12 months | 12 | 32,224 | 0.61 | 2.5% | 4.1% | ridge |
| Imported Brandies, Woodbury County, dollars, 3 months | 3 | 121 | 0.62 | 14.4% | 23.3% | ridge |
| Flavored Rum, Iowa, liters, 3 months | 3 | 4,798 | 0.71 | 8.2% | 11.7% | ridge |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 12 | 330 | 0.73 | 6.9% | 9.5% | ridge |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 6 | 532 | 0.79 | 12.8% | 16.1% | ridge |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 12 | 117 | 0.80 | 14.6% | 18.2% | ridge |
| All liquor, statewide | 6 | 207,812 | 0.81 | 3.9% | 4.9% | ridge |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 6 | 14,663 | 0.81 | 4.0% | 5.0% | ridge |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 12 | 5 | 0.85 | 75.3% | 89.6% | lightgbm |
| Luxco Inc, Lee County, dollars, 6 months | 6 | 203 | 0.87 | 23.0% | 26.3% | ridge |
| Imported Vodkas, Iowa, liters, 6 months | 6 | 5,350 | 0.90 | 16.2% | 18.0% | ridge |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 6 | 94 | 0.91 | 22.0% | 24.3% | ridge |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 12 | 317 | 0.92 | 18.9% | 20.5% | lightgbm |
| American Flavored Vodka, Fayette County, dollars, 12 months | 12 | 49 | 0.92 | 22.5% | 24.7% | ridge |
| Jim Beam Brands, Johnson County, bottles, 12 months | 12 | 785 | 0.95 | 12.7% | 13.5% | ridge |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 12 | 4,445 | 0.98 | 6.0% | 6.2% | ridge |
| Luxco Inc, Dickinson County, dollars, 12 months | 12 | 195 | 1.01 | 16.9% | 16.7% | ridge |
| American Brandies, Marshall County, dollars, 6 months | 6 | 59 | 1.02 | 24.0% | 23.5% | ridge |
| Diageo Americas, Warren County, liters, 6 months | 6 | 366 | 1.03 | 13.3% | 12.9% | ridge |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 6 | 51 | 1.04 | 16.2% | 15.6% | ridge |
| Black Velvet 200 ml, Boone County, liters, 6 months | 6 | 2 | 1.05 | 74.3% | 70.8% | ridge |
| Proximo, O'Brien County, liters, 6 months | 6 | 51 | 1.06 | 31.0% | 29.4% | ridge |
| Irish Whiskies, Iowa, bottles, 12 months | 12 | 2,554 | 1.06 | 6.5% | 6.2% | ridge |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 12 | 343 | 1.08 | 12.0% | 11.1% | ridge |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 3 | 761 | 1.12 | 16.4% | 14.7% | lightgbm |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 12 | 18 | 1.27 | 63.8% | 49.8% | ridge |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 12 | 12 | 1.27 | 20.1% | 15.8% | ridge |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 6 | 3 | 1.44 | 145.2% | 98.7% | lightgbm |
