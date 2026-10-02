# Differential test: AI-written SQL vs the slot-filling reference

18 requests: 11 identical month by month, 7 AI-written queries wrong. The first run also found a reference bug, since fixed: The reference agent's product search showed at most 60 products, so for Crown Royal (91 products) and Jack Daniel's (80) it quietly left out the smallest ones. Fixed: the search now says when more products match, and the request form can name a whole brand. Details and both queries: docs/differential.html.

| request | result | all history | last 12 months |
|---|---|---|---|
| monthly forecast of Tito's minis in Des Moines for the next 5 months | AI missed renumbered items | -13.9% | under 0.1% |
| How many bottles of each Tito's mini item will sell statewide over the next 6 months? | AI missed renumbered items | -13.0% | under 0.1% |
| Forecast Tito's minis ordered by Hy-Vee #3 BDI in Des Moines for the next 6 months | AI missed renumbered items | -14.7% | under 0.1% |
| Monthly forecast of Tito's vodka bottles in Polk County for the next 5 months | AI missed renumbered items | -3.5% | -0.1% |
| How many bottles of whiskey will Ames stores order next month? | AI used old category codes | -1.5% | -0.6% |
| Monthly liters of Crown Royal in Mount Pleasant for the next 4 months | AI missed some products | under 0.1% | under 0.1% |
| Forecast Jack Daniel's bottle sales in Iowa City for the next 4 months | AI missed some products | under 0.1% | under 0.1% |
| Tito's bottles in St. Ansgar for the next 4 months | identical |  |  |
| Bottled in bond bourbon bottles statewide, next 3 months | identical |  |  |
| American vodka sales dollars for each of the five largest counties, next 6 months | identical |  |  |
| How many bottles of cream liqueur will Iowa stores order for the holidays? | identical |  |  |
| Monthly bottle sales for all Diageo products in Scott County, next 6 months | identical |  |  |
| What revenue should we expect from Fireball in Linn County next quarter? | identical |  |  |
| Hawkeye Vodka bottles in Johnson County, next 5 months | identical |  |  |
| Forecast ready-to-drink cocktail bottles statewide for the next 6 months | identical |  |  |
| Total liters of liquor sold statewide over the next 6 months | identical |  |  |
| Forecast Tennessee whiskey bottles across Iowa for the next 3 months | identical |  |  |
| Forecast vodka | identical |  |  |
