# Experiment: recent averages as inputs (on top of season, holiday weeks and active stores)

A = today's inputs, B = A + season (+ holiday weeks, weekly) + active stores, C = B + recent averages (last 4 and
13 periods). Error relative to the same period last year on the test window (below 1 beats it).

**monthly** (30 forecasts): beat last year A 23, B 22, C 22; median A 0.880, B 0.892, C 0.904.

**weekly** (30 forecasts): beat last year A 28, B 29, C 29; median A 0.857, B 0.826, C 0.822.

| forecast | month A | month B | month C | week A | week B | week C |
|---|---|---|---|---|---|---|
| All liquor, statewide | 0.969 | 0.961 | 0.964 | 0.965 | 0.950 | 0.946 |
| Imported Brandies, Woodbury County, dollars, 3 months | 0.813 | 0.813 | 0.674 | 1.020 | 0.876 | 0.913 |
| American Brandies, Marshall County, dollars, 6 months | 0.848 | 0.802 | 0.857 | 0.776 | 0.756 | 0.773 |
| Jim Beam Brands, Johnson County, bottles, 12 months | 0.882 | 1.009 | 0.895 | 0.958 | 0.796 | 0.796 |
| Southern Comfort Mini 50 ml, Iowa, bottles, 12 months | 0.861 | 0.825 | 0.828 | 0.699 | 0.619 | 0.633 |
| Heaven Hill Brands, Poweshiek County, liters, 12 months | 1.133 | 1.037 | 1.005 | 0.816 | 0.846 | 0.881 |
| Imported Cordials & Liqueur, Iowa, bottles, 12 months | 1.428 | 1.067 | 1.315 | 0.860 | 0.908 | 0.915 |
| American Brandies, Iowa, dollars, 12 months | 0.456 | 0.389 | 0.525 | 0.887 | 0.803 | 0.792 |
| American Flavored Vodka, Fayette County, dollars, 12 months | 0.835 | 0.868 | 1.047 | 0.854 | 0.840 | 0.856 |
| Brown Forman Corp., Buena Vista County, dollars, 6 months | 0.958 | 1.025 | 0.976 | 0.899 | 0.892 | 0.882 |
| American Vodkas, Iowa, bottles, 12 months | 0.707 | 0.716 | 0.714 | 0.869 | 0.857 | 0.825 |
| Black Velvet 200 ml, Boone County, liters, 6 months | 0.938 | 0.959 | 0.956 | 0.751 | 0.731 | 0.732 |
| Kinky Blue Mini 50 ml, O'Brien County, liters, 6 months | 0.998 | 1.000 | 0.852 | 1.016 | 1.122 | 1.149 |
| Irish Whiskies, Iowa, bottles, 12 months | 1.545 | 1.260 | 1.226 | 0.955 | 0.939 | 0.909 |
| Captain Morgan Original Spiced 1000 ml, Story County, bottles, 12 months | 0.989 | 1.111 | 1.093 | 0.893 | 0.885 | 0.828 |
| Hawkeye Vodka Mini 50 ml, Iowa, liters, 6 months | 0.846 | 0.730 | 0.725 | 0.648 | 0.577 | 0.578 |
| Imported Vodkas, Iowa, liters, 6 months | 0.859 | 0.857 | 0.806 | 0.857 | 0.919 | 0.899 |
| Brown Forman Corp., Black Hawk County, dollars, 12 months | 0.731 | 0.773 | 0.761 | 0.828 | 0.832 | 0.829 |
| Flavored Rum, Iowa, liters, 3 months | 0.805 | 0.768 | 0.774 | 0.962 | 0.895 | 0.874 |
| Diageo Americas, Warren County, liters, 6 months | 1.070 | 1.048 | 1.011 | 0.974 | 0.985 | 0.916 |
| Luxco Inc, Lee County, dollars, 6 months | 0.838 | 0.711 | 0.895 | 0.780 | 0.740 | 0.747 |
| American Schnapps, Iowa, bottles, 3 months | 0.552 | 0.651 | 0.650 | 0.917 | 0.704 | 0.819 |
| 99 Bananas 100 ml, Woodbury County, liters, 12 months | 1.441 | 0.855 | 1.161 | 0.806 | 0.753 | 0.756 |
| Smirnoff 80Prf Mini 50 ml, Marion County, bottles, 12 months | 0.812 | 0.816 | 0.815 | 0.786 | 0.799 | 0.802 |
| Captain Morgan Original Spiced 375 ml, Iowa, bottles, 3 months | 0.945 | 0.975 | 0.992 | 0.733 | 0.755 | 0.770 |
| Proximo, O'Brien County, liters, 6 months | 0.877 | 0.955 | 0.965 | 0.707 | 0.707 | 0.692 |
| Luxco Inc, Dickinson County, dollars, 12 months | 1.037 | 1.010 | 1.069 | 0.997 | 0.940 | 0.953 |
| Jim Beam Apple Mini 50 ml, Iowa, liters, 12 months | 1.143 | 0.990 | 0.930 | 0.767 | 0.803 | 0.794 |
| Bacardi Usa Inc, Marshall County, dollars, 6 months | 0.949 | 0.916 | 0.912 | 0.803 | 0.807 | 0.768 |
| Straight Bourbon Whiskies, Iowa, bottles, 6 months | 0.825 | 0.867 | 0.779 | 0.857 | 0.820 | 0.814 |

Conclusion (2026-10-02): recent averages are not adopted (weekly C equals B, 14 better and 16 worse; monthly C worse
than B). Weekly: adopt B (season, holiday weeks, active stores offered to model selection): median 0.857 -> 0.826,
29 of 30 beat last year. Monthly: keep A for now; B lowers the mean (0.936 -> 0.892, fixing the worst forecasts) but
beats last year less often (22 vs 23) with a slightly worse median; season alone is a candidate for a later test.
