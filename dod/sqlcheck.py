"""The one gate every LLM-written SQL statement passes before it touches the database."""
import sqlglot
from sqlglot import exp

AGENT_SCHEMAS = {"sales", "ref", "meta"}   # what the read-only agent role can see


def check_sql(sql):
    """Allow exactly one SELECT whose tables all live in schemas the agent can read."""
    try:
        stmts = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as e:
        return f"does not parse: {str(e).splitlines()[0]}"
    if len(stmts) != 1 or not isinstance(stmts[0], (exp.Select, exp.Union, exp.With)) and stmts[0].find(exp.Select) is None:
        return "not a single SELECT"
    if any(stmts[0].find(t) for t in (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter)):
        return "contains a write"
    ctes = {c.alias for c in stmts[0].find_all(exp.CTE)}
    for table in stmts[0].find_all(exp.Table):
        if table.name in ctes:
            continue
        if table.db not in AGENT_SCHEMAS:
            return f"reads {table.db or '(no schema)'}.{table.name}, outside sales/ref/meta"
    return None
