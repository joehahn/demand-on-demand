"""The forecast request, fully resolved to warehouse codes. The agent writes one after resolving the user's words
against the database; specs/*.json are hand-written examples."""
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

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
    horizon: int = Field(ge=1, le=MAX_HORIZON)
    product: Product
    region: Region
    series_by: Literal["none", "county", "city", "item", "category"] = "none"
    start: str = "2016-01-01"
    features: list[Literal["calendar", "population"]] = Field(default_factory=lambda: ["calendar", "population"])

    @property
    def slug(self):
        return re.sub(r"[^a-z0-9]+", "_", self.title.lower()).strip("_")[:60]


def load(path):
    return Spec(**json.loads(Path(path).read_text()))
