"""The answer key for AI-written SQL: the correct monthly history for every test request.

    python evals/build_answers.py

evals/answer_cases.json holds each test request with a request form (dod/spec.Spec) reviewed by hand: which products,
which place, which measure, and in "definition" any choice a person had to make (e.g. "Fireball minis" = every Fireball
product in 50 ml bottles). Fixed, tested code (dod/panel.build_sql) turns each form into monthly totals, written to
evals/answers.json. No AI is involved, so the answers do not change unless the forms or the warehouse do.

A forecast's history is right if its daily (or weekly) totals, summed by month, equal these in every month. That
checks which rows were selected and summed; the grain and horizon are checked against "expect" in the cases file.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dod import db, panel  # noqa: E402
from dod.spec import Spec  # noqa: E402

HERE = Path(__file__).parent


def norm(name):
    """Series names compared loosely: upper case, single spaces, no ' COUNTY'."""
    return " ".join(str(name).upper().replace(" COUNTY", "").split())


def monthly(form, last_month):
    """The form's monthly series through the last complete month: months with no orders are 0, months before a
    series' first order are null (compare them as 0)."""
    spec = Spec.model_validate(form)
    wide = panel.to_wide(db.query(*panel.build_sql(spec)), spec.start, last_month)
    if spec.series_by == "none":
        wide.columns = ["TOTAL"]
    else:
        wide.columns = [norm(panel.labels_for(spec, [c]).get(c, c)) for c in wide]
    return {c: {str(m.date()): None if v != v else round(float(v), 2) for m, v in wide[c].items()} for c in wide}


if __name__ == "__main__":
    _, last_month = panel.data_end()
    answers = {}
    for case in json.loads((HERE / "answer_cases.json").read_text()):
        if case["expect"]["status"] != "ok":
            continue
        series = monthly(case["form"], last_month)
        answers[case["id"]] = {"through": str(last_month.date()), "series": series}
        total = sum(v or 0 for s in series.values() for v in s.values())
        print(f"  {case['id']:26s} {len(series):2d} series  {total:16,.0f}")
    (HERE / "answers.json").write_text(json.dumps(answers, indent=1))
    print(f"{len(answers)} answers through {last_month.date()} -> evals/answers.json")
