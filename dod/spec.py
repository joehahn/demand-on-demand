"""The forecast request, fully resolved to warehouse codes. The agent writes one after resolving the user's words
against the database; specs/*.json are hand-written examples."""
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MAX_HORIZON = 12
TARGETS = ("sales_bottles", "sales_dollars", "sales_liters")


class Scope(BaseModel):
    kind: str
    codes: list[str] = Field(default_factory=list)
    label: str


class Product(Scope):
    kind: Literal["all", "item", "category", "vendor", "name"]   # item codes are product families (family_item_no);
    # name codes are the words of one brand: every product whose name contains all of them


class Region(Scope):
    kind: Literal["statewide", "county", "city", "store"]


class Spec(BaseModel):
    title: str
    target: Literal[TARGETS] = "sales_bottles"
    horizon: int = Field(ge=1, le=52)
    grain: Literal["month", "week", "quarter"] = "month"   # the slot-filling agent always uses months
    product: Product
    region: Region
    series_by: Literal["none", "county", "city", "item", "category"] = "none"
    start: str = "2016-01-01"
    features: list[Literal["calendar", "population", "season", "holiday_weeks", "stores"]] = Field(
        default_factory=lambda: ["calendar", "population"])

    @model_validator(mode="after")
    def horizon_fits_grain(self):
        """At most one year ahead: 12 months, 52 weeks or 4 quarters."""
        most = {"month": MAX_HORIZON, "week": 52, "quarter": 4}[self.grain]
        if self.horizon > most:
            raise ValueError(f"horizon {self.horizon} is more than {most} {self.grain}s")
        return self

    @property
    def slug(self):
        return re.sub(r"[^a-z0-9]+", "_", self.title.lower()).strip("_")[:60]


def load(path):
    return Spec(**json.loads(Path(path).read_text()))
