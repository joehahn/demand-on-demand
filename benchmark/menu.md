# Experiment: one input menu for every forecast

Error relative to the same period last year on the Testing period (below 1 beats it). A = today's menus (months: calendar with month number, population; weeks: sine and cosine, holiday flags, active stores); B = one menu (sine and cosine, business days and holiday flags, population, active stores); C = B, but LightGBM sees the month number.

**monthly** (30 forecasts)

| arm | beat last year | median | mean |
|---|---|---|---|
| A | 20 | 0.909 | 0.952 |
| B | 17 | 0.935 | 0.931 |
| C | 18 | 0.921 | 0.913 |

B vs A: better on 18, worse on 12, same on 0.

C vs A: better on 21, worse on 9, same on 0.

**weekly** (30 forecasts)

| arm | beat last year | median | mean |
|---|---|---|---|
| A | 28 | 0.833 | 0.845 |
| B | 28 | 0.845 | 0.878 |
| C | 29 | 0.833 | 0.840 |

B vs A: better on 12, worse on 14, same on 4.

C vs A: better on 16, worse on 10, same on 4.

| forecast | month A | month B | month C | week A | week B | week C |
|---|---|---|---|---|---|---|
| All liquor, statewide | 0.901 | 0.806 | 0.806 | 0.955 | 0.958 | 0.933 |
| Imported Brandies, Woodbury County, dollars, 3 months | 0.776 | 0.617 | 0.617 | 1.037 | 1.025 | 1.025 |
| American Brandies, Marshall County, dollars, 6 months | 0.891 | 1.020 | 1.020 | 0.767 | 0.767 | 0.767 |
| Jim Beam Brands, Johnson County, bottles, 12 months | 0.882 | 0.948 | 0.948 | 0.787 | 0.754 | 0.754 |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 0.814 | 0.729 | 0.729 | 0.786 | 0.784 | 0.784 |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 0.983 | 0.797 | 0.797 | 0.931 | 0.846 | 0.846 |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 1.496 | 1.097 | 0.980 | 0.890 | 0.883 | 0.883 |
| American Brandies, Iowa, dollars, 12 months | 0.411 | 0.448 | 0.448 | 0.767 | 0.902 | 0.902 |
| American Flavored Vodka, Fayette County, dollars, 12 months | 1.061 | 0.922 | 0.922 | 0.834 | 0.834 | 0.834 |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 1.037 | 1.036 | 1.036 | 0.880 | 0.891 | 0.891 |
| American Vodkas, Iowa, bottles, 12 months | 0.707 | 0.608 | 0.608 | 0.824 | 0.847 | 0.824 |
| Black Velvet 200 ml, Boone County, liters, 6 months | 0.938 | 1.036 | 1.052 | 0.753 | 0.754 | 0.754 |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 0.998 | 1.248 | 1.436 | 1.086 | 1.790 | 0.958 |
| Irish Whiskies, Iowa, bottles, 12 months | 1.420 | 1.056 | 1.056 | 0.906 | 0.967 | 0.967 |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 1.333 | 1.364 | 1.269 | 0.893 | 0.931 | 0.931 |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 0.846 | 0.795 | 0.795 | 0.586 | 0.585 | 0.585 |
| Imported Vodkas, Iowa, liters, 6 months | 0.898 | 0.959 | 0.899 | 0.869 | 0.875 | 0.868 |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 1.019 | 0.828 | 0.921 | 0.848 | 0.833 | 0.833 |
| Flavored Rum, Iowa, liters, 3 months | 0.778 | 0.698 | 0.705 | 0.867 | 0.845 | 0.848 |
| Diageo Americas, Warren County, liters, 6 months | 1.038 | 1.034 | 1.034 | 0.957 | 0.970 | 0.974 |
| Luxco Inc, Lee County, dollars, 6 months | 0.890 | 0.752 | 0.872 | 0.769 | 0.823 | 0.823 |
| American Schnapps, Iowa, bottles, 3 months | 0.653 | 0.544 | 0.544 | 0.788 | 0.781 | 0.695 |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 1.138 | 1.360 | 1.069 | 0.820 | 0.799 | 0.807 |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 0.890 | 0.895 | 0.849 | 0.800 | 0.800 | 0.800 |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 1.092 | 1.118 | 1.118 | 0.823 | 0.741 | 0.741 |
| Proximo, O'Brien County, liters, 6 months | 0.958 | 1.097 | 1.056 | 0.688 | 0.766 | 0.766 |
| Luxco Inc, Dickinson County, dollars, 12 months | 1.037 | 1.015 | 1.015 | 0.946 | 0.934 | 0.966 |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 0.873 | 1.401 | 1.078 | 0.816 | 0.963 | 0.780 |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 0.918 | 0.897 | 0.908 | 0.831 | 0.834 | 0.834 |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 0.875 | 0.810 | 0.810 | 0.857 | 0.857 | 0.828 |
