"""The request as the agent read it: its SQL for the order lines, plus a plain description of what is forecast
(title, measure, product, place, breakout, grain, horizon). The SQL decides the numbers; the description only labels
the dashboard."""
import re
from typing import Literal

from pydantic import BaseModel, Field

TARGETS = ("sales_bottles", "sales_dollars", "sales_liters")
MAX_AHEAD = {"week": 52, "fortnight": 26, "month": 12, "quarter": 4, "half": 2, "year": 1}


class Plan(BaseModel):
    title: str
    sql: str
    target: Literal[TARGETS] = "sales_bottles"
    grain: Literal["week", "fortnight", "month", "quarter", "half", "year"] = "month"
    horizon: int = Field(ge=1, le=52)
    product: str                      # readable name, e.g. "Tito's minis (50 ml)"
    place: str                        # readable name, e.g. "Des Moines"
    series_by: str = "none"           # "none" for one total, else what each series is (county, city, item, ...)
    request: str = ""
    assumptions: list[str] = Field(default_factory=list)
    start: str = "2016-01-01"
    features: list[str] = Field(default_factory=list)   # input groups offered to model selection (set by fixed code)

    @property
    def slug(self):
        return re.sub(r"[^a-z0-9]+", "_", self.title.lower()).strip("_")[:60]

    @property
    def model_grain(self):
        """What the models forecast: weeks or months, added up into longer periods by dod/periods.py. This is the
        simple count; for calendar periods dod/forecast.py works out the exact months from where the data ends."""
        from .periods import MAX_STEPS, PERIODS
        grain, size, _ = PERIODS[self.grain]
        return grain, min(size * self.horizon, MAX_STEPS[grain])
