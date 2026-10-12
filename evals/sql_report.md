# AI-written SQL scored against the answer key

34 requests x 3 runs = 102 runs. Passed: **102 of 102** (data right in 102, reading right in 102). Requests right in every run: 34 of 34. Cost $1.92, median 12 s and 4 tool calls per request.

| request | what the answer key counts | passed | what went wrong |
|---|---|---|---|
| Monthly forecast of Tito's vodka bottles in Polk County for the next 5 months | Tito's Handmade Vodka (all sizes); Polk County; bottles | 3/3 |  |
| How many bottles of each Tito's mini item will sell statewide over the next 6 months? | Tito's Handmade Vodka Mini items; Iowa; bottles, one series per item | 3/3 |  |
| monthly forecast of Tito's minis in Des Moines for the next 5 months | Tito's Handmade Vodka Minis (50ml, single and 4-pack); Des Moines; bottles | 3/3 |  |
| Monthly liters of Crown Royal in Mount Pleasant for the next 4 months | Crown Royal (all sizes/variants); Mount Pleasant; liters | 3/3 |  |
| Forecast Tennessee whiskey bottles across Iowa for the next 3 months | Tennessee Whiskies; Iowa; bottles | 3/3 |  |
| American vodka sales dollars for each of the five largest counties, next 6 months | American Vodkas, flavored included; Polk, Linn, Scott, Johnson, Black Hawk counties; dollars, one series per county. American vodka includes American Flavored Vodka | 3/3 |  |
| Forecast Tito's vodka sales in Chicago for the next 5 months | should be declined | 3/3 |  |
| Forecast total Iowa liquor sales dollars for the next 24 months | should be declined | 3/3 |  |
| Forecast Jack Daniel's bottle sales in Iowa City for the next 4 months | Jack Daniel's (all products); Iowa City; bottles | 3/3 |  |
| What revenue should we expect from Fireball in Linn County next quarter? | Fireball (all products); Linn County; dollars | 3/3 |  |
| Total liters of liquor sold statewide over the next 6 months | All products; Iowa statewide; liters | 3/3 |  |
| Monthly bottle sales for all Diageo products in Scott County, next 6 months | Diageo Americas; Scott County; bottles | 3/3 |  |
| Tito's bottles in St. Ansgar for the next 4 months | Tito's Handmade Vodka (all sizes); Saint Ansgar; bottles | 3/3 |  |
| Bottled in bond bourbon bottles statewide, next 3 months | Bottled in Bond Bourbon; Iowa statewide; bottles | 3/3 |  |
| Forecast each Tito's 100 ml item statewide for the next 6 months | Tito's 100 ml; Iowa; bottles, one series per item. One Tito's 100 ml product, first ordered Nov 2025: the harness declines it (too little history) | 3/3 |  |
| Forecast ready-to-drink cocktail bottles statewide for the next 6 months | Cocktails/RTD; Iowa; bottles | 3/3 |  |
| Hawkeye Vodka bottles in Johnson County, next 5 months | Hawkeye Vodka (all sizes); Johnson County; bottles | 3/3 |  |
| How many bottles of whiskey will Ames stores order next month? | Whiskey (all whiskey categories, excluding whiskey liqueur); Ames; bottles. Whiskey = every category named WHISK..., not Whiskey Liqueur | 3/3 |  |
| Forecast vodka | Vodka (all categories); Iowa; bottles. No horizon or grain given: any reading is fine | 3/3 |  |
| How many bottles of cream liqueur will Iowa stores order for the holidays? | Cream liqueurs; Iowa; bottles. 'for the holidays' = through December (data ends Aug 31): 4 months or about 17 weeks | 3/3 |  |
| Forecast Tito's minis ordered by Hy-Vee #3 BDI in Des Moines for the next 6 months | Tito's Handmade Vodka minis (50ml); Hy-Vee #3 / BDI / Des Moines; bottles | 3/3 |  |
| Weekly forecast of Tito's minis in Des Moines for the next 8 weeks | Tito's Handmade Vodka Minis (50ml, single and 4-pack); Des Moines; bottles | 3/3 |  |
| Quarterly forecast of Fireball revenue in Linn County for the next 2 quarters | Fireball (all sizes); Linn County; dollars | 3/3 |  |
| show me weekly forecast of Cream liqueur bottles sold across all of iowa, twelve weeks out | Cream Liqueurs; Iowa; bottles | 3/3 |  |
| Total Iowa vodka sales dollars for the next year | Vodka (all types); Iowa; dollars. Every product whose current category is a vodka category; 'next year' = the next 12 months | 3/3 |  |
| Weekly bottles of liquor ordered by all Hy-Vee stores in Iowa for the next 8 weeks | All liquor; All Hy-Vee stores; bottles. Every store whose name contains HY-VEE (207 stores: food stores, gas, wine and spirits, Dollar Fresh) | 3/3 |  |
| Weekly Crown Royal bottles statewide for the next 10 weeks | Crown Royal (all sizes/variants); Iowa; bottles | 3/3 |  |
| Jack Daniel's sales dollars in Polk County, next 6 months | Jack Daniel's (all products); Polk County; dollars. Every product whose name has the words JACK and DANIELS (or DANIEL'S), including barrel picks | 3/3 |  |
| Hawkeye Vodka bottles statewide by week, next 8 weeks | Hawkeye Vodka (all sizes); Iowa; bottles | 3/3 |  |
| Captain Morgan liters in Scott County for the next 3 quarters | Captain Morgan (all products); Scott County; liters. Every product named CAPTAIN MORGAN, including its ready-to-drink cocktails | 3/3 |  |
| Fireball minis statewide, next 6 months | Fireball minis (50 ml); Iowa; bottles. Every Fireball product in 50 ml bottles, whether or not its name says MINI | 3/3 |  |
| Black Velvet bottles in Woodbury County for the next 4 months | Black Velvet (all varieties and sizes); Woodbury County; bottles | 3/3 |  |
| Weekly whiskey liqueur bottles statewide for the next 6 weeks | Whiskey Liqueur; Iowa; bottles. Every product whose current category is Whiskey Liqueur | 3/3 |  |
| Spiced rum sales dollars in Black Hawk County for the next 4 months | Spiced Rum; Black Hawk County; dollars. Every product whose current category is Spiced Rum (1062400) | 3/3 |  |
