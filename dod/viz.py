"""Shared page and chart styling for every HTML page in the project (dataviz reference palette,
light and dark mode via CSS tokens)."""
import html

import pandas as pd
import plotly.graph_objects as go

# Reference palette from the dataviz skill (validated slots, fixed order). Text and gridline colors
# are overridden in CSS so the same figures read correctly in light and dark mode.

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
GRID = "rgba(137,135,129,0.25)"


def style(fig, title, ytitle=None, height=340, legend=False):
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=15)),
        height=height, margin=dict(l=60, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', size=12),
        showlegend=legend, legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, title=ytitle)
    return fig


def line(x, y, name, color, dash=None):
    return go.Scatter(x=x, y=y, name=name, mode="lines", line=dict(color=color, width=2, dash=dash))


def table(df, fmt=None):
    fmt = fmt or {}
    numeric = {c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])}
    head = "".join(f'<th class="{"num" if c in numeric else ""}">{html.escape(str(c))}</th>' for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            s = fmt[c](v) if c in fmt and pd.notna(v) else ("" if pd.isna(v) else str(v))
            num = pd.api.types.is_number(v) and not isinstance(v, bool)
            cells.append(f'<td class="{"num" if num else ""}">{html.escape(s)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'



PAGE_CSS = """
:root { color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --line:#e1e0d9; --border:rgba(11,11,11,0.10); --accent:#2a78d6; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --line:#2c2c2a; --border:rgba(255,255,255,0.10); --accent:#3987e5; } }
:root[data-theme="dark"] { color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --line:#2c2c2a; --border:rgba(255,255,255,0.10); --accent:#3987e5; }
* { box-sizing: border-box; }
body { margin:0; background:var(--page); color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1040px; margin:0 auto; padding:32px 16px 64px; }
h1 { font-size:26px; margin:0 0 6px; } h2 { font-size:19px; margin:36px 0 8px; } h3 { font-size:15px; margin:20px 0 6px; }
pre { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:10px; overflow-x:auto; font-size:12px; color:var(--ink2); }
details { margin:6px 0; } summary { cursor:pointer; }
p, li { color:var(--ink2); max-width:760px; } a { color:var(--accent); }
.card { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:8px 10px; margin:10px 0; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin:16px 0; }
.tile { background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }
.tile .v { font-size:24px; font-weight:600; color:var(--ink); } .tile .k { font-size:13px; color:var(--muted); }
.tbl { overflow-x:auto; } table { border-collapse:collapse; width:100%; font-size:13px; }
th, td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:600; } td { color:var(--ink2); }
th.num, td.num { text-align:right; font-variant-numeric:tabular-nums; }
.note { font-size:13px; color:var(--muted); }
.asked { font-size:17px; color:var(--ink); font-style:italic; margin:4px 0 6px; }
.readas { font-size:15px; color:var(--ink); margin:0 0 2px; }
.readas span { font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); margin-right:6px; }
.headline { font-size:16px; color:var(--ink); margin:10px 0 12px; max-width:760px; }
td { vertical-align:top; word-break:break-word; }
.fixlink { font-size:13px; color:var(--muted); margin:2px 0 14px; }
.warn { font-size:14px; color:var(--ink); border-left:3px solid #fab219; padding:4px 10px; }
/* plotly draws its own text/grid colors; point them at the theme tokens */
.card .main-svg :is(.xtick, .ytick, .g-xtitle, .g-ytitle, .gtitle, .legendtext, .cbaxis, .cbtitle) text,
.card .main-svg :is(.gtitle, .legendtext) { fill:var(--ink2) !important; }
.card .main-svg .gridlayer path, .card .main-svg .xgrid, .card .main-svg .ygrid { stroke:var(--line) !important; }
.card .hoverlayer text { fill:#0b0b0b !important; }
footer { margin-top:48px; font-size:13px; color:var(--muted); }
"""


class Plots:
    """Renders plotly figures into cards; plotly.js is loaded once, from the CDN, with the first figure.
    numbered=True prefixes each title with its figure number, in the order the figures are rendered.
    toolbar=False hides Plotly's hover toolbar (zoom, pan, download), which can cover controls at a chart's top right."""
    def __init__(self, numbered=False, toolbar=True):
        self.count = 0
        self.numbered = numbered
        self.toolbar = toolbar

    def __call__(self, fig):
        first = self.count == 0
        self.count += 1
        if self.numbered:
            fig.update_layout(title_text=f"Figure {self.count}. {fig.layout.title.text}")
        return '<div class="card">' + fig.to_html(full_html=False, include_plotlyjs="cdn" if first else False,
                                                   config={"displaylogo": False, "responsive": True,
                                                           "displayModeBar": self.toolbar}) + "</div>"


def page(title, body):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{PAGE_CSS}</style></head>
<body><main>{body}</main></body></html>"""
