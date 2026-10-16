# Forecast-accuracy benchmark

45 forecasts, each scored against "same month last year" (the baseline) over a 24-month test window they never trained on, 6s median each. They come from a random sample of the warehouse (30: products, categories and vendors, statewide and by county), a set picked for high volume (10) and five popular brands statewide asked for by quarter or by year (forecast by month and summed).

- Beat the baseline: **26 of 45**; median relative error **0.92** (below 1 is better); median monthly error (WAPE, weighted absolute percentage error: total absolute error divided by total actual sales) model 12.8%, baseline 13.4%.
- **Sales volume decides when ML succeeds.** With a handful of orders a month, one order more or less swings the total, and neither the model nor the baseline can predict that. With high volume, the model wins most of the time, and its losses are narrow:

| bottles per month | forecasts | beat the baseline | median relative error | median model error | median baseline error |
|---|---|---|---|---|---|
| under 1,000 | 9 | 2 | 1.05 | 31.0% | 29.4% |
| 1,000 to 50,000 | 15 | 10 | 0.92 | 13.3% | 14.7% |
| over 50,000 | 21 | 14 | 0.81 | 5.5% | 8.3% |

![Relative error vs bottles per month: low-volume forecasts scatter around or above 1, high-volume ones mostly below](accuracy_vs_volume.svg)

| forecast | horizon | bottles per month | relative error | model error | baseline error | model |
|---|---|---|---|---|---|---|
| All liquor, statewide | 6 | 3,236,877 | 0.81 | 3.9% | 4.9% | ridge |
| Sazerac Company  Inc, Iowa, dollars, 12 months | 12 | 795,029 | 0.47 | 3.9% | 8.3% | ridge |
| American Vodkas, Iowa, bottles, 12 months | 12 | 626,991 | 0.61 | 2.5% | 4.1% | ridge |
| Fireball, Iowa, dollars, next 12 months, as one year | 1 year | 509,007 | 0.86 | 5.0% | 5.8% | ridge |
| Canadian Whiskies, Iowa, dollars, 6 months | 6 | 303,077 | 1.06 | 15.2% | 14.4% | ridge |
| Luxco Inc, Iowa, liters, 6 months | 6 | 206,366 | 0.33 | 2.4% | 7.3% | ridge |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 6 | 172,984 | 0.81 | 4.0% | 5.0% | ridge |
| All liquor, Black Hawk County, bottles, 12 months | 12 | 171,904 | 0.77 | 6.4% | 8.3% | ridge |
| Captain Morgan, Iowa, bottles, next 4 quarters | 4 quarters | 133,453 | 1.03 | 10.3% | 10.0% | ridge |
| Tito's, Iowa, bottles, next 4 quarters | 4 quarters | 128,867 | 0.67 | 5.2% | 7.7% | ridge |
| Crown Royal, Iowa, dollars, next 4 quarters | 4 quarters | 122,481 | 1.12 | 20.9% | 18.6% | ridge |
| American Schnapps, Iowa, bottles, 3 months | 3 | 117,567 | 0.54 | 4.7% | 8.6% | lightgbm |
| Mccormick Distilling Co., Iowa, liters, 12 months | 12 | 98,894 | 0.78 | 4.9% | 6.3% | ridge |
| Brown Forman Corp., Iowa, bottles, 6 months | 6 | 98,575 | 1.05 | 5.5% | 5.3% | ridge |
| Jack Daniel's, Iowa, liters, next 12 months, as one year | 1 year | 90,069 | 1.00 | 13.4% | 13.4% | ridge |
| Blended Whiskies, Iowa, dollars, 6 months | 6 | 87,840 | 0.95 | 14.7% | 15.5% | ridge |
| Imported Vodkas, Iowa, liters, 6 months | 6 | 81,717 | 0.90 | 16.2% | 18.0% | ridge |
| American Brandies, Iowa, dollars, 12 months | 12 | 70,397 | 0.45 | 4.3% | 9.6% | ridge |
| American Cordials & Liqueur, Iowa, liters, 12 months | 12 | 58,633 | 1.07 | 9.3% | 8.7% | ridge |
| White Rum, Iowa, liters, 6 months | 6 | 55,644 | 1.03 | 7.5% | 7.2% | ridge |
| Cream Liqueurs, Iowa, bottles, 12 months | 12 | 52,308 | 0.68 | 7.0% | 10.3% | ridge |
| Flavored Rum, Iowa, liters, 3 months | 3 | 48,020 | 0.71 | 8.2% | 11.7% | ridge |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 12 | 45,122 | 0.98 | 6.0% | 6.2% | ridge |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 6 | 34,894 | 0.79 | 12.8% | 16.1% | ridge |
| Irish Whiskies, Iowa, bottles, 12 months | 12 | 30,949 | 1.06 | 6.5% | 6.2% | ridge |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 12 | 21,732 | 0.73 | 6.9% | 9.5% | ridge |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 12 | 17,133 | 1.08 | 12.0% | 11.1% | ridge |
| Jim Beam Brands, Johnson County, bottles, 12 months | 12 | 12,694 | 0.95 | 12.7% | 13.5% | ridge |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 3 | 10,604 | 1.12 | 16.4% | 14.7% | lightgbm |
| Diageo Americas, Warren County, liters, 6 months | 6 | 5,829 | 1.03 | 13.3% | 12.9% | ridge |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 12 | 4,404 | 0.92 | 18.9% | 20.5% | lightgbm |
| Luxco Inc, Lee County, dollars, 6 months | 6 | 2,936 | 0.87 | 23.0% | 26.3% | ridge |
| Luxco Inc, Dickinson County, dollars, 12 months | 12 | 2,492 | 1.01 | 16.9% | 16.7% | ridge |
| Imported Brandies, Woodbury County, dollars, 3 months | 3 | 1,441 | 0.62 | 14.4% | 23.3% | ridge |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 12 | 1,166 | 0.80 | 14.6% | 18.2% | ridge |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 6 | 1,003 | 0.91 | 22.0% | 24.3% | ridge |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 12 | 771 | 1.27 | 20.1% | 15.8% | ridge |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 6 | 609 | 1.04 | 16.2% | 15.6% | ridge |
| American Brandies, Marshall County, dollars, 6 months | 6 | 521 | 1.02 | 24.0% | 23.5% | ridge |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 12 | 398 | 1.27 | 63.8% | 49.8% | ridge |
| American Flavored Vodka, Fayette County, dollars, 12 months | 12 | 389 | 0.92 | 22.5% | 24.7% | ridge |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 12 | 267 | 0.85 | 75.3% | 89.6% | lightgbm |
| Proximo, O'Brien County, liters, 6 months | 6 | 244 | 1.06 | 31.0% | 29.4% | ridge |
| Black Velvet 200 ml, Boone County, liters, 6 months | 6 | 66 | 1.05 | 74.3% | 70.8% | ridge |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 6 | 50 | 1.44 | 145.2% | 98.7% | lightgbm |
