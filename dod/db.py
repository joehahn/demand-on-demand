"""Database access. The harness reads with the same read-only role as the agent: least privilege."""
import os
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


def connect():
    return psycopg.connect(os.environ["DOD_AGENT_DSN"], autocommit=True)


def query(sql, params=None):
    """Run one SELECT and return a DataFrame; Postgres numeric comes back as float."""
    with connect() as conn:
        cur = conn.execute(sql, params)
        df = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
    for col in df.columns:
        if df[col].dtype == object and len(df) and type(df[col].dropna().iloc[0]).__name__ == "Decimal":
            df[col] = df[col].astype(float)
    return df
