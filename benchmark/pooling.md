# Experiment: pooling and monthly inputs, before retiring slot filling

Error relative to the same month last year on the test window (below 1 beats it). A = today (calendar and population inputs, pooling with 15 companion counties); B = inputs, no pooling; C = no inputs, no pooling.

**All 30 forecasts**

| run | beat last year | median | mean |
|---|---|---|---|
| A today | 23 | 0.880 | 0.936 |
| B no pooling | 20 | 0.909 | 0.952 |
| C no inputs, no pooling | 13 | 1.009 | 1.014 |

**The 30 forecasts where pooling was offered** (statewide ones pool with counties too); a pooled model was chosen in 22

| run | beat last year | median | mean |
|---|---|---|---|
| A today | 23 | 0.880 | 0.936 |
| B no pooling | 20 | 0.909 | 0.952 |

B vs A: better on 11, worse on 13, same on 6. C vs B: better on 11, worse on 18, same on 1.

| forecast | A | B | C | pooled | inputs kept (A) |
|---|---|---|---|---|---|
| All liquor, statewide | 0.969 | 0.901 | 1.314 | yes | calendar,population |
| Imported Brandies, Woodbury County, dollars, 3 months | 0.813 | 0.776 | 0.903 | yes | calendar,population |
| American Brandies, Marshall County, dollars, 6 months | 0.848 | 0.891 | 1.074 | yes | calendar,population |
| Jim Beam Brands, Johnson County, bottles, 12 months | 0.882 | 0.882 | 1.287 |  | calendar,population |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 0.861 | 0.814 | 0.885 | yes | calendar,population |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 1.133 | 0.983 | 1.039 | yes | calendar,population |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 1.428 | 1.496 | 1.330 | yes | calendar,population |
| American Brandies, Iowa, dollars, 12 months | 0.456 | 0.411 | 0.741 |  | calendar,population |
| American Flavored Vodka, Fayette County, dollars, 12 months | 0.835 | 1.061 | 1.056 | yes | calendar,population |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 0.958 | 1.037 | 1.045 | yes | calendar,population |
| American Vodkas, Iowa, bottles, 12 months | 0.707 | 0.707 | 0.752 |  | calendar,population |
| Black Velvet 200 ml, Boone County, liters, 6 months | 0.938 | 0.938 | 0.953 |  | calendar |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 0.998 | 0.998 | 1.212 |  | calendar,population |
| Irish Whiskies, Iowa, bottles, 12 months | 1.545 | 1.420 | 1.327 | yes | calendar,population |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 0.989 | 1.333 | 1.211 | yes | calendar,population |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 0.846 | 0.846 | 0.869 |  | calendar |
| Imported Vodkas, Iowa, liters, 6 months | 0.859 | 0.898 | 0.903 | yes | calendar |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 0.731 | 1.019 | 0.865 | yes | calendar,population |
| Flavored Rum, Iowa, liters, 3 months | 0.805 | 0.778 | 0.803 |  | calendar,population |
| Diageo Americas, Warren County, liters, 6 months | 1.070 | 1.038 | 0.957 | yes | calendar |
| Luxco Inc, Lee County, dollars, 6 months | 0.838 | 0.890 | 1.008 | yes | calendar |
| American Schnapps, Iowa, bottles, 3 months | 0.552 | 0.653 | 1.041 | yes | calendar,population |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 1.441 | 1.138 | 1.011 | yes | calendar,population |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 0.812 | 0.890 | 0.796 | yes | population |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 0.945 | 1.092 | 1.055 | yes | calendar |
| Proximo, O'Brien County, liters, 6 months | 0.877 | 0.958 | 1.007 | yes | calendar |
| Luxco Inc, Dickinson County, dollars, 12 months | 1.037 | 1.037 | 1.037 |  | calendar,population |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 1.143 | 0.873 | 0.873 | yes | calendar |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 0.949 | 0.918 | 0.916 | yes | calendar,population |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 0.825 | 0.875 | 1.136 | yes | calendar |
