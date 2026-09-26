"""Decide which approved register issues apply to a request, and what the harness does about each."""
from . import db

# What the harness does for each register rule. Rules that need the data are applied in panel.py;
# this module only decides applicability and records the decision.
BY_DESIGN = {
    "etl_fixed": "Handled by the loader before the data reached the warehouse.",
    "use_line_id": "Satisfied by design: the harness sums order lines and never counts invoice_id.",
    "derive_price": "Not needed: this forecast uses no price feature.",
}


def load():
    return db.query("SELECT * FROM meta.known_issues WHERE status = 'approved' ORDER BY severity, issue_id")


def assess(spec, issues):
    """Return one decision per register issue: applied, context, or not relevant, with the reason."""
    used = spec.used_columns()
    decisions = []
    for _, issue in issues.iterrows():
        overlap = sorted(set(issue.scope_columns) & used)
        rule, d = issue.mitigation_rule, {"issue_id": issue.issue_id, "title": issue.title,
                                           "severity": issue.severity, "rule": issue.mitigation_rule,
                                           "params": issue.mitigation_params or {}}
        if rule == "exclude_zero_lines":
            d.update(action="applied", note="Zero-bottle and zero-dollar lines are excluded in the aggregation SQL.")
        elif rule in BY_DESIGN:
            d.update(action="by_design", note=BY_DESIGN[rule])
        elif rule == "min_date":
            if overlap:
                d.update(action="applied", note=f"Series start moved to {d['params'].get('date')} because this "
                                                f"request uses {', '.join(overlap)}.")
            else:
                d.update(action="not_relevant", note="This request does not filter or group by the affected columns.")
        elif rule == "cap_outliers":
            if spec.target in issue.scope_columns:
                d.update(action="applied", note=f"Monthly {spec.target} values are capped at "
                                                f"{d['params'].get('k', 5)} robust deviations from the seasonal level.")
            else:
                d.update(action="not_relevant", note=f"Affects {', '.join(issue.scope_columns)}, not {spec.target}.")
        elif rule == "carry_forward_reference":
            if "population" in spec.features:
                d.update(action="applied", note="Latest published county population is carried forward to later years.")
            else:
                d.update(action="not_relevant", note="This forecast uses no Census feature.")
        else:  # flag_only
            if overlap:
                d.update(action="context", note=f"Shown for context; touches {', '.join(overlap)}.")
            else:
                d.update(action="not_relevant", note="Does not touch the columns this request uses.")
        decisions.append(d)
    return decisions


def start_date(spec, decisions):
    """The latest min_date among applied register rules and the request's own mitigations."""
    dates = [spec.start] + [d["params"]["date"] for d in decisions if d["action"] == "applied" and d["rule"] == "min_date"]
    dates += [m.params["date"] for m in spec.mitigations if m.rule == "min_date" and "series" not in m.params]
    return max(dates)
