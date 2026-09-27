# Forecast-accuracy benchmark

30 forecasts sampled from the warehouse (seed 0), 30 completed, in 480s (14s median each).

- Beat "same month last year" on the 24-month test window: **21 of 30** (70%)
- Median error relative to that baseline: **0.92** (below 1 is better)
- Median monthly error (WAPE): model 14.1%, baseline 17.3%

| forecast | horizon | relative error | model error | baseline error | model |
|---|---|---|---|---|---|
| Hennessy Vs 750 ml, O'Brien County, liters, 6 months | 6 | 0.48 | 33.2% | 69.6% | ridge |
| American Brandies, Iowa, liters, 6 months | 6 | 0.60 | 4.6% | 7.7% | ridge |
| Hawkeye Vodka 1750 ml, Marion County, bottles, 12 months | 12 | 0.60 | 12.3% | 20.4% | lightgbm |
| Jack Daniels Old #7 Black Label 1000 ml, Iowa, liters, 12 months | 12 | 0.69 | 12.5% | 18.0% | ridge |
| Blended Whiskies, Fayette County, dollars, 12 months | 12 | 0.76 | 13.9% | 18.3% | ridge |
| Brown Forman Corp., O'Brien County, liters, 6 months | 6 | 0.76 | 42.6% | 55.9% | ridge |
| Imported Vodkas, Marshall County, dollars, 6 months | 6 | 0.78 | 21.1% | 27.0% | ridge |
| Smirnoff 80Prf 375 ml, Woodbury County, liters, 12 months | 12 | 0.81 | 21.7% | 26.9% | ridge |
| Proximo, Marshall County, dollars, 6 months | 6 | 0.82 | 24.9% | 30.5% | ridge |
| Luxco Inc, Lee County, dollars, 6 months | 6 | 0.84 | 22.1% | 26.3% | ridge |
| Imported Schnapps, Iowa, bottles, 12 months | 12 | 0.87 | 7.0% | 8.0% | ridge |
| Fireball Cinnamon Whiskey 200 ml, Iowa, bottles, 12 months | 12 | 0.88 | 13.4% | 15.3% | ridge |
| Jim Beam Brands, Johnson County, bottles, 12 months | 12 | 0.89 | 13.4% | 15.1% | ridge |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 12 | 0.91 | 17.1% | 18.8% | lightgbm |
| Imported Vodkas, Iowa, dollars, 12 months | 12 | 0.92 | 9.6% | 10.5% | lightgbm |
| Five O'Clock Vodka 375 ml, Boone County, liters, 6 months | 6 | 0.92 | 82.4% | 88.9% | ridge |
| Malibu Coconut 1000 ml, Iowa, bottles, 3 months | 3 | 0.93 | 13.3% | 14.3% | lightgbm |
| American Vodkas, Iowa, bottles, 12 months | 12 | 0.94 | 3.8% | 4.0% | lightgbm |
| E & J Gallo Winery, Black Hawk County, dollars, 12 months | 12 | 0.94 | 20.6% | 21.7% | ridge |
| All liquor, statewide | 6 | 0.97 | 4.7% | 4.9% | ridge |
| American Flavored Vodka, Iowa, bottles, 3 months | 3 | 0.98 | 7.5% | 7.7% | lightgbm |
| Flavored Rum, Woodbury County, dollars, 3 months | 3 | 1.03 | 25.8% | 25.2% | lightgbm |
| Luxco Inc, Dickinson County, dollars, 12 months | 12 | 1.04 | 17.3% | 16.7% | ridge |
| Diageo Americas, Warren County, liters, 6 months | 6 | 1.04 | 14.3% | 13.8% | ridge |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 6 | 1.05 | 5.2% | 5.0% | ridge |
| Cream Liqueurs, Iowa, liters, 3 months | 3 | 1.16 | 17.4% | 15.0% | lightgbm |
| E & J Gallo Winery, Buena Vista County, dollars, 6 months | 6 | 1.20 | 49.1% | 40.7% | ridge |
| Barton Vodka 1000 ml, Story County, bottles, 12 months | 12 | 1.23 | 98.2% | 79.3% | ridge |
| Titos Handmade Vodka 750 ml, Iowa, liters, 6 months | 6 | 1.50 | 7.9% | 5.3% | ridge |
| Irish Whiskies, Iowa, bottles, 12 months | 12 | 1.73 | 10.0% | 5.8% | ridge |
