"""The forecast request, fully resolved to warehouse codes. In Phase 3 specs are written by hand
(specs/*.json); in Phase 4 the agent writes them after resolving the user's words against the database."""
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

MAX_HORIZON = 12
TARGETS = ("sales_bottles", "sales_dollars", "sales_liters")
RULES = ("min_date", "exclude_series", "stitch_successor", "normalize_values", "cap_outliers", "flag_only")


class Scope(BaseModel):
    kind: str
    codes: list[str] = Field(default_factory=list)
    label: str


class Product(Scope):
    kind: Literal["all", "item", "category", "vendor"]


class Region(Scope):
    kind: Literal["statewide", "county", "city", "store"]


class Mitigation(BaseModel):
    """A request-level fix, chosen from the harness's closed vocabulary."""
    rule: Literal[RULES]
    params: dict = Field(default_factory=dict)
    reason: str = ""
    source: Literal["spec", "agent", "register"] = "spec"


class Spec(BaseModel):
    title: str
    target: Literal[TARGETS] = "sales_bottles"
    horizon: int = Field(ge=1, le=MAX_HORIZON)
    product: Product
    region: Region
    series_by: Literal["none", "county", "city", "item", "category"] = "none"
    start: str = "2016-01-01"
    features: list[Literal["calendar", "population"]] = Field(default_factory=lambda: ["calendar", "population"])
    mitigations: list[Mitigation] = Field(default_factory=list)

    @property
    def slug(self):
        return re.sub(r"[^a-z0-9]+", "_", self.title.lower()).strip("_")[:60]

    def used_columns(self):
        """Warehouse columns this request filters, groups or sums on; decides which register issues apply."""
        cols = {self.target, "ordered_on"}
        cols |= {"item": {"item_no"}, "category": {"category_code"}, "vendor": {"vendor_no"}, "all": set()}[self.product.kind]
        cols |= {"county": {"county_fips", "county_name"}, "city": {"city"}, "store": {"store_no"},
                 "statewide": set()}[self.region.kind]
        cols |= {"county": {"county_fips", "county_name"}, "city": {"city"}, "item": {"item_no"},
                 "category": {"category_code"}, "none": set()}[self.series_by]
        if "population" in self.features:
            cols |= {"population", "year"}
        return cols


def load(path):
    return Spec(**json.loads(Path(path).read_text()))
