# Differential test: AI-written SQL vs the slot-filling reference

18 requests: 11 identical month by month, 5 AI-written queries wrong, 2 reference bugs. Details and both queries: docs/differential.html.

| request | result | all history | last 12 months |
|---|---|---|---|
| monthly forecast of Tito's minis in Des Moines for the next 5 months | AI missed renumbered items | -13.9% | +0.0% |
| How many bottles of each Tito's mini item will sell statewide over the next 6 months? | AI missed renumbered items | -13.0% | +0.0% |
| Tito's bottles in St. Ansgar for the next 4 months | AI missed renumbered items | -0.1% | +0.0% |
| Forecast Tito's minis ordered by Hy-Vee #3 BDI in Des Moines for the next 6 months | AI missed renumbered items | -14.7% | +0.0% |
| Bottled in bond bourbon bottles statewide, next 3 months | AI used old category codes | +13.0% | +0.4% |
| Monthly liters of Crown Royal in Mount Pleasant for the next 4 months | Reference bug | +0.5% | +0.9% |
| Forecast Jack Daniel's bottle sales in Iowa City for the next 4 months | Reference bug | +0.0% | +0.3% |
| How many bottles of whiskey will Ames stores order next month? | identical |  |  |
| How many bottles of cream liqueur will Iowa stores order for the holidays? | identical |  |  |
| Monthly bottle sales for all Diageo products in Scott County, next 6 months | identical |  |  |
| What revenue should we expect from Fireball in Linn County next quarter? | identical |  |  |
| Hawkeye Vodka bottles in Johnson County, next 5 months | identical |  |  |
| Forecast ready-to-drink cocktail bottles statewide for the next 6 months | identical |  |  |
| Total liters of liquor sold statewide over the next 6 months | identical |  |  |
| Forecast Tennessee whiskey bottles across Iowa for the next 3 months | identical |  |  |
| Monthly forecast of Tito's vodka bottles in Polk County for the next 5 months | identical |  |  |
| Forecast vodka | identical |  |  |
| American vodka sales dollars for each of the five largest counties, next 6 months | identical |  |  |
