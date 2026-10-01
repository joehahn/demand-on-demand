"""
data_dictionary.py: publish docs/data_dictionary.html, the warehouse exactly as the AI agent sees it.

    python data_dictionary.py

Reads the same table and column descriptions the agent reads at the start of every request (dod.agent.schema_rows:
Postgres comments written by load_data.py meta from TABLE_NOTES and COLUMN_NOTES), so the page cannot drift from
what the agent is told. Connects with the agent's read-only login.
"""
import html
from pathlib import Path

import pandas as pd

from dod.agent import schema_rows
from dod.viz import page, table

OUT = Path(__file__).parent / "docs" / "data_dictionary.html"


def build():
    rows = schema_rows()
    parts = []
    for tbl, g in rows.groupby("tbl", sort=False):
        about = g.table_note.iloc[0] if isinstance(g.table_note.iloc[0], str) else ""
        cols = pd.DataFrame({"column": g.column_name, "type": g.data_type, "description": g.note.fillna("")})
        parts.append(f'<h2 id="{html.escape(tbl)}">{html.escape(tbl)}</h2><p>{html.escape(about)}</p>'
                     + table(cols, bold=("column",)))
    body = f"""
<h1>Iowa liquor warehouse: data dictionary</h1>
<p>This is exactly what the AI agent is told about the warehouse at the start of every forecast request:
{rows.tbl.nunique()} tables and {len(rows)} columns, each described in a sentence. The agent uses it to know which
tables and columns hold products, places and sales; its search tools then find the actual names (a product, a city),
and it fills in a forecast request. It never writes the SQL: the harness does. The descriptions are written once in the
loader and stored in the database, so this page, the agent and any SQL client all read the same text. Raw tables and
credentials are not described because the agent cannot reach them.</p>
<p><a href="index.html">Back to demand-on-demand</a> &middot; <a href="data_exploration.html">data exploration</a>
&middot; <a href="data_fixes.html">data fixes</a></p>
{"".join(parts)}
<footer>Data: Iowa Liquor Sales, State of Iowa, via the Iowa Data Hub, CC BY 4.0; modified (see the data fixes page).
County population and income: U.S. Census Bureau. Not endorsed by the State of Iowa.</footer>"""
    return page("Iowa Liquor Data Dictionary", body)


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT.relative_to(OUT.parent.parent)} ({OUT.stat().st_size / 1e3:.0f} KB)")
