"""Fetch extra FRED series for the market_context worker and save data/macro_extra.csv.

    .venv/Scripts/python data/fetch_fred_extra.py [--upload]

Same long format as macro_rates.csv: date, series_id, value, unit, frequency, label, source.
Values: https://fred.stlouisfed.org/graph/fredgraph.csv ; label/units/frequency are read from each series page
(https://fred.stlouisfed.org/series/<id>), not typed by hand. Values are FRED's current (revised) vintage.
Range starts one year before the starter window so 12-month look-back rules work from its first day.
--upload also copies the file to s3://$DATA_BUCKET/data/macro_extra.csv.
"""
import io
import os
import re
import sys
import urllib.request
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

SERIES = ["T10Y2Y", "SAHMREALTIME", "RECPROUSM156N", "INDPRO", "VIXCLS", "BAMLH0A0HYM2", "UMCSENT"]
START, END = "2020-11-12", "2026-11-12"
OUT = Path(__file__).resolve().parent / "macro_extra.csv"


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def meta(sid: str) -> dict:
    """Label, units and frequency scraped from the FRED series page."""
    html = get(f"https://fred.stlouisfed.org/series/{sid}").decode("utf-8", "replace")
    title = re.search(r"<title>(.*?)\s*\(" + re.escape(sid) + r"\)", html, re.S)
    unit = re.search(r'series-meta-value-units">\s*(.*?)\s*<.*?default-text">\s*(.*?)\s*<', html, re.S)
    freq = re.search(r'series-meta-value-frequency">\s*([A-Za-z]+)', html)
    if not (title and unit and freq):
        raise ValueError(f"{sid}: could not read metadata from FRED page")
    return {"label": title.group(1).strip(), "unit": f"{unit.group(1)}, {unit.group(2)}",
            "frequency": freq.group(1).lower()}


def main():
    frames = []
    for sid in SERIES:
        m = meta(sid)
        df = pd.read_csv(io.BytesIO(get(
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={START}&coed={END}")))
        df.columns = ["date", "value"]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna()
        df = df.assign(series_id=sid, unit=m["unit"], frequency=m["frequency"], label=m["label"],
                       source="FRED, Federal Reserve Bank of St. Louis")
        frames.append(df)
        print(f"{sid}: {len(df)} rows {df.date.min()} -> {df.date.max()} | {m['frequency']} | {m['unit']} | {m['label']}")
    out = pd.concat(frames)[["date", "series_id", "value", "unit", "frequency", "label", "source"]]
    out.to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(out)} rows)")
    if "--upload" in sys.argv:
        import boto3
        load_dotenv(OUT.parent.parent / ".env")
        bucket = os.environ["DATA_BUCKET"]
        boto3.client("s3", region_name="us-east-1").upload_file(str(OUT), bucket, "data/macro_extra.csv")
        print(f"uploaded to s3://{bucket}/data/macro_extra.csv")


if __name__ == "__main__":
    main()
