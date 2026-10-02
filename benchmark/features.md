# Experiment: new model inputs (season, holiday weeks, active stores)

Each new input group is offered to model selection, which keeps it only if it helps on the model-selection
window; scored on the test window as error relative to the same period last year (below 1 beats it).

**monthly** (30 forecasts): beat last year 23 -> 22; median 0.880 -> 0.892; better on 16, worse on 14, unchanged on 0.

**weekly** (30 forecasts): beat last year 28 -> 29; median 0.857 -> 0.826; better on 19, worse on 10, unchanged on 1.

| forecast | month A | month B | kept | week A | week B | kept |
|---|---|---|---|---|---|---|
| All liquor, statewide | 0.969 | 0.961 | calendar,season,stores | 0.965 | 0.950 | season,stores |
| Imported Brandies, Woodbury County, dollars, 3 months | 0.813 | 0.813 | calendar,population | 1.020 | 0.876 | holiday_weeks,stores |
| American Brandies, Marshall County, dollars, 6 months | 0.848 | 0.802 | calendar,population,season,stores | 0.776 | 0.756 | stores |
| Jim Beam Brands, Johnson County, bottles, 12 months | 0.882 | 1.009 | calendar,stores | 0.958 | 0.796 | season,stores |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 0.861 | 0.825 | calendar,season,stores | 0.699 | 0.619 | season |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 1.133 | 1.037 | calendar,population,season,stores | 0.816 | 0.846 | season,holiday_weeks,stores |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 1.428 | 1.067 | calendar,population,season,stores | 0.860 | 0.908 | season,holiday_weeks,stores |
| American Brandies, Iowa, dollars, 12 months | 0.456 | 0.389 | calendar,population,season | 0.887 | 0.803 | season,stores |
| American Flavored Vodka, Fayette County, dollars, 12 months | 0.835 | 0.868 | calendar,stores | 0.854 | 0.840 | stores |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 0.958 | 1.025 | season | 0.899 | 0.892 | season,stores |
| American Vodkas, Iowa, bottles, 12 months | 0.707 | 0.716 | calendar,stores | 0.869 | 0.857 | season,holiday_weeks,stores |
| Black Velvet 200 ml, Boone County, liters, 6 months | 0.938 | 0.959 | calendar,season,stores | 0.751 | 0.731 | season,holiday_weeks,stores |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 0.998 | 1.000 | calendar,population,season,stores | 1.016 | 1.122 | season,stores |
| Irish Whiskies, Iowa, bottles, 12 months | 1.545 | 1.260 | population,season | 0.955 | 0.939 | season,stores |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 0.989 | 1.111 | population,season | 0.893 | 0.885 | season,stores |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 0.846 | 0.730 | calendar,population,season,stores | 0.648 | 0.577 | season,holiday_weeks,stores |
| Imported Vodkas, Iowa, liters, 6 months | 0.859 | 0.857 | calendar,population,season,stores | 0.857 | 0.919 | holiday_weeks,stores |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 0.731 | 0.773 | calendar,season | 0.828 | 0.832 | holiday_weeks |
| Flavored Rum, Iowa, liters, 3 months | 0.805 | 0.768 | calendar,season,stores | 0.962 | 0.895 | stores |
| Diageo Americas, Warren County, liters, 6 months | 1.070 | 1.048 | calendar,season | 0.974 | 0.985 | season |
| Luxco Inc, Lee County, dollars, 6 months | 0.838 | 0.711 | calendar,population,season | 0.780 | 0.740 | season,stores |
| American Schnapps, Iowa, bottles, 3 months | 0.552 | 0.651 | calendar,season | 0.917 | 0.704 | season,holiday_weeks,stores |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 1.441 | 0.855 | calendar,population,season,stores | 0.806 | 0.753 | season,holiday_weeks,stores |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 0.812 | 0.816 | season,stores | 0.786 | 0.799 | season,stores |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 0.945 | 0.975 | calendar,population,season,stores | 0.733 | 0.755 | stores |
| Proximo, O'Brien County, liters, 6 months | 0.877 | 0.955 | calendar,population,season,stores | 0.707 | 0.707 | none |
| Luxco Inc, Dickinson County, dollars, 12 months | 1.037 | 1.010 | calendar,population | 0.997 | 0.940 | season,holiday_weeks |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 1.143 | 0.990 | calendar | 0.767 | 0.803 | season,holiday_weeks |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 0.949 | 0.916 | calendar,population,stores | 0.803 | 0.807 | season,holiday_weeks,stores |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 0.825 | 0.867 | calendar,population,season,stores | 0.857 | 0.820 | season |
