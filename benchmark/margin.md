# Experiment: keep an input only if it clearly helps (model.KEEP_MARGIN)

Error relative to the same period last year on the test window (below 1 beats it). Weekly: none = no inputs; m0, m2, m5 = season, holiday weeks and active stores offered, kept only if the error without them is at least 0%, 2% or 5% higher on the model-selection window. Monthly: calendar and population offered.

**weekly** (30 forecasts)

| run | beat last year | median | mean |
|---|---|---|---|
| week_none | 28 | 0.857 | 0.855 |
| week_m0 | 29 | 0.826 | 0.828 |
| week_m2 | 29 | 0.849 | 0.839 |
| week_m5 | 28 | 0.854 | 0.847 |

**monthly** (30 forecasts)

| run | beat last year | median | mean |
|---|---|---|---|
| month_m0 | 23 | 0.880 | 0.936 |
| month_m2 | 22 | 0.880 | 0.936 |

| forecast | week none | week m0 | week m2 | week m5 | week m2 kept | month m0 | month m2 | month m2 kept |
|---|---|---|---|---|---|---|---|---|
| All liquor, statewide | 0.965 | 0.950 | 0.950 | 1.056 | season,stores | 0.969 | 0.884 | calendar |
| Imported Brandies, Woodbury County, dollars, 3 months | 1.020 | 0.876 | 0.882 | 0.882 | stores | 0.813 | 0.813 | calendar |
| American Brandies, Marshall County, dollars, 6 months | 0.776 | 0.756 | 0.776 | 0.776 | none | 0.848 | 0.849 | calendar |
| Jim Beam Brands, Johnson County, bottles, 12 months | 0.958 | 0.796 | 0.911 | 0.911 | none | 0.882 | 0.919 | population |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 0.699 | 0.619 | 0.632 | 0.632 | none | 0.861 | 0.861 | calendar,population |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 0.816 | 0.846 | 0.847 | 0.924 | stores | 1.133 | 1.133 | calendar,population |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 0.860 | 0.908 | 0.891 | 0.891 | stores | 1.428 | 1.273 | calendar |
| American Brandies, Iowa, dollars, 12 months | 0.887 | 0.803 | 0.790 | 0.807 | season | 0.456 | 0.573 | calendar |
| American Flavored Vodka, Fayette County, dollars, 12 months | 0.854 | 0.840 | 0.840 | 0.836 | stores | 0.835 | 0.837 | calendar |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 0.899 | 0.892 | 0.899 | 0.899 | none | 0.958 | 1.078 | none |
| American Vodkas, Iowa, bottles, 12 months | 0.869 | 0.857 | 0.857 | 0.867 | season,holiday_weeks,stores | 0.707 | 0.707 | calendar,population |
| Black Velvet 200 ml, Boone County, liters, 6 months | 0.751 | 0.731 | 0.750 | 0.750 | none | 0.938 | 0.938 | calendar |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 1.016 | 1.122 | 1.159 | 1.159 | season | 0.998 | 0.998 | calendar,population |
| Irish Whiskies, Iowa, bottles, 12 months | 0.955 | 0.939 | 0.955 | 0.955 | none | 1.545 | 1.545 | calendar,population |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 0.893 | 0.885 | 0.892 | 0.892 | none | 0.989 | 0.989 | calendar,population |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 0.648 | 0.577 | 0.658 | 0.658 | stores | 0.846 | 0.846 | calendar |
| Imported Vodkas, Iowa, liters, 6 months | 0.857 | 0.919 | 0.858 | 0.858 | none | 0.859 | 0.859 | calendar |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 0.828 | 0.832 | 0.851 | 0.851 | none | 0.731 | 0.730 | calendar |
| Flavored Rum, Iowa, liters, 3 months | 0.962 | 0.895 | 0.895 | 0.895 | stores | 0.805 | 0.805 | calendar,population |
| Diageo Americas, Warren County, liters, 6 months | 0.974 | 0.985 | 0.985 | 0.985 | season | 1.070 | 1.070 | calendar |
| Luxco Inc, Lee County, dollars, 6 months | 0.780 | 0.740 | 0.740 | 0.724 | season,stores | 0.838 | 0.838 | calendar |
| American Schnapps, Iowa, bottles, 3 months | 0.917 | 0.704 | 0.709 | 0.759 | holiday_weeks,stores | 0.552 | 0.507 | calendar |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 0.806 | 0.753 | 0.752 | 0.752 | stores | 1.441 | 1.441 | calendar,population |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 0.786 | 0.799 | 0.798 | 0.798 | stores | 0.812 | 0.817 | none |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 0.733 | 0.755 | 0.755 | 0.755 | stores | 0.945 | 0.945 | calendar |
| Proximo, O'Brien County, liters, 6 months | 0.707 | 0.707 | 0.707 | 0.707 | none | 0.877 | 0.877 | calendar |
| Luxco Inc, Dickinson County, dollars, 12 months | 0.997 | 0.940 | 0.963 | 0.963 | season | 1.037 | 1.037 | calendar,population |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 0.767 | 0.803 | 0.837 | 0.837 | none | 1.143 | 1.143 | calendar |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 0.803 | 0.807 | 0.790 | 0.782 | season | 0.949 | 0.949 | calendar,population |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 0.857 | 0.820 | 0.857 | 0.857 | none | 0.825 | 0.825 | calendar |
