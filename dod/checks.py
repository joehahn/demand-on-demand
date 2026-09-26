"""Slice-level data checks: problems specific to THIS request that no register can list in advance.

The checks are deterministic. Each finding carries a suggested fix from the closed vocabulary; the
harness does not apply it by itself. In Phase 3 a hand-written spec decides; in Phase 4 the agent reads
the findings and decides, and the dashboard shows which were applied."""
import numpy as np
import pandas as pd

from . import db

SHIFT_WINDOW = 6          # months on each side for level-shift detection
SHIFT_RATIO = 2.0         # a level change of 2x (or 1/2x) is flagged
OUTLIER_K = 5.0           # robust deviations from the seasonal level


def _finding(check, series, severity, message, rule=None, params=None, evidence=None):
    return {"check": check, "series": series, "severity": severity, "message": message,
            "suggested_rule": rule, "suggested_params": params or {}, "evidence": evidence or {}}


def series_checks(wide, labels):
    """Start/stop, zero runs, level shifts and outlier months in each forecast series."""
    out = []
    for c in wide:
        s = wide[c].dropna()
        name = labels.get(c, c)
        nz = s[s > 0]
        if nz.empty:
            out.append(_finding("empty_series", c, "high", f"{name} has no sales in the window.", "exclude_series", {"series": [c]}))
            continue
        first, last = nz.index.min(), nz.index.max()
        if first > s.index.min() + pd.offsets.MonthBegin(2):
            out.append(_finding("late_start", c, "medium",
                                f"{name} has no sales before {first:%Y-%m}; earlier zeros are not real demand.",
                                "min_date", {"date": f"{first:%Y-%m-%d}", "series": [c]},
                                {"first_sale": f"{first:%Y-%m}"}))
        if last < s.index.max():
            out.append(_finding("stopped", c, "high", f"{name} has had no sales since {last:%Y-%m}.",
                                "exclude_series", {"series": [c]}, {"last_sale": f"{last:%Y-%m}"}))
        inner = s[(s.index > first) & (s.index < last)]
        zeros = int((inner == 0).sum())
        if zeros:
            out.append(_finding("zero_months", c, "low", f"{name} has {zeros} month(s) with zero sales mid-history.",
                                "flag_only", evidence={"months": [f"{d:%Y-%m}" for d in inner[inner == 0].index][:12]}))
        # level shift: compare medians of the windows either side of each month
        s_nz = s[(s.index >= first) & (s.index <= last)]  # only the months the series was selling
        if len(s_nz) >= 2 * SHIFT_WINDOW + 1:
            before = s_nz.rolling(SHIFT_WINDOW).median().shift(1)
            after = s_nz[::-1].rolling(SHIFT_WINDOW).median()[::-1]
            ratio = (after / before.replace(0, np.nan)).dropna()
            big = ratio[(ratio > SHIFT_RATIO) | (ratio < 1 / SHIFT_RATIO)]
            if not big.empty:
                at = np.log(big.clip(lower=1e-9)).abs().idxmax()  # the biggest shift, up or down
                out.append(_finding("level_shift", c, "high",
                                    f"{name} changes level about {ratio[at]:.1f}x around {at:%Y-%m}. If that is a "
                                    "data artifact (recoding, reclassification), start the series after it.",
                                    "min_date", {"date": f"{at:%Y-%m-%d}", "series": [c]},
                                    {"month": f"{at:%Y-%m}", "ratio": round(float(ratio[at]), 2)}))
        # outliers against a centered 13-month median
        level = s_nz.rolling(13, center=True, min_periods=7).median()
        resid = s_nz - level
        mad = 1.4826 * np.nanmedian(np.abs(resid - np.nanmedian(resid)))
        if mad:
            z = (resid / mad).dropna()
            spikes = z[z.abs() > OUTLIER_K]
            if not spikes.empty:
                out.append(_finding("outlier_months", c, "medium",
                                    f"{name} has {len(spikes)} month(s) beyond {OUTLIER_K:g} robust deviations.",
                                    "cap_outliers", {"k": OUTLIER_K},
                                    {"months": {f"{d:%Y-%m}": round(float(v), 1) for d, v in spikes.items()}}))
    return out


def item_checks(spec, start):
    """Items in the product scope that stop, start, or replace one another inside the window."""
    if spec.product.kind != "item":
        return []
    items = db.query("""
        SELECT l.item_no, i.item_desc, i.bottle_volume_ml, min(l.ordered_on) AS first_on, max(l.ordered_on) AS last_on,
               sum(l.sales_bottles) AS bottles
        FROM sales.invoice_line l JOIN sales.item i USING (item_no)
        WHERE l.item_no = ANY(%s) AND l.ordered_on >= %s GROUP BY 1, 2, 3""", (spec.product.codes, start))
    if items.empty:
        return []
    items["first_on"], items["last_on"] = pd.to_datetime(items.first_on), pd.to_datetime(items.last_on)
    window_end = items.last_on.max()
    out = []
    aggregated = spec.series_by != "item"
    for old in items.itertuples():
        if (window_end - old.last_on).days < 45:
            continue  # still selling
        # successor: same description and bottle size, first sold within 60 days of the old item's last sale
        cands = items[(items.item_desc == old.item_desc) & (items.bottle_volume_ml == old.bottle_volume_ml)
                      & (items.item_no != old.item_no)]
        cands = cands[(cands.first_on - old.last_on).dt.days.between(-30, 60)]
        if not cands.empty:
            new = cands.sort_values("bottles", ascending=False).iloc[0]
            harmless = " Both items are summed into one series here, so this has no effect." if aggregated else ""
            out.append(_finding("item_renumbered", old.item_no, "low" if aggregated else "high",
                                f"{old.item_desc} {old.bottle_volume_ml} ml was renumbered: item {old.item_no} last sold "
                                f"{old.last_on:%Y-%m-%d}, item {new.item_no} first sold {new.first_on:%Y-%m-%d}.{harmless}",
                                None if aggregated else "stitch_successor",
                                None if aggregated else {"column": "item_no", "from": old.item_no, "to": new.item_no},
                                {"old": old.item_no, "new": new.item_no}))
        else:
            out.append(_finding("item_discontinued", old.item_no, "low",
                                f"{old.item_desc} {old.bottle_volume_ml} ml (item {old.item_no}) stopped selling "
                                f"{old.last_on:%Y-%m-%d}.", "flag_only",
                                evidence={"bottles": float(old.bottles)}))
    return out


def store_checks(spec, start):
    """How much of the region's volume comes from stores that opened or closed inside the window."""
    region = {"county": "s.county_fips = ANY(%(r)s)", "city": "s.city = ANY(%(r)s)",
              "store": "s.store_no = ANY(%(r)s)", "statewide": "TRUE"}[spec.region.kind]
    df = db.query(f"""
        SELECT count(*) AS stores,
               count(*) FILTER (WHERE first_order_on > %(start)s::date + 90) AS opened,
               count(*) FILTER (WHERE last_order_on < (SELECT max(last_order_on) - 90 FROM sales.store)) AS closed
        FROM sales.store s WHERE {region} AND last_order_on >= %(start)s""", {"r": spec.region.codes, "start": start})
    r = df.iloc[0]
    if r.stores and (r.opened + r.closed) / r.stores > 0.2:
        return [_finding("store_churn", "region", "low",
                         f"{int(r.opened)} of {int(r.stores)} stores in {spec.region.label} opened and {int(r.closed)} "
                         "closed during the window, so part of the trend is store count, not demand per store.",
                         "flag_only", evidence={k: int(v) for k, v in r.items()})]
    return []


def run(spec, panel):
    findings = series_checks(panel.series, panel.labels) + item_checks(spec, panel.start) + store_checks(spec, panel.start)
    # mark which findings the spec's mitigations address: fixed by the suggested rule, or reviewed and
    # deliberately left alone (a flag_only naming the check, e.g. {"check": "level_shift", "series": ["total"]})
    for f in findings:
        fixed = f["suggested_rule"] not in (None, "flag_only") and any(m.rule == f["suggested_rule"] and
                    all(m.params.get(k) == v for k, v in f["suggested_params"].items() if k != "date")
                    for m in spec.mitigations)
        reviewed = [m for m in spec.mitigations if m.rule == "flag_only" and m.params.get("check") == f["check"]
                    and (not m.params.get("series") or f["series"] in m.params["series"])]
        f["addressed"] = fixed or bool(reviewed)
        no_effect = f["suggested_rule"] is None  # e.g. a renumbering inside one summed series
        f["addressed"] = f["addressed"] or no_effect
        f["resolution"] = "fixed" if fixed else ("reviewed" if reviewed else ("no_effect" if no_effect else "open"))
        f["review_note"] = reviewed[0].reason if reviewed and not fixed else ""
    return findings
