"""Fetch fund size (total net assets, AUM) for the ETF baskets and save data/fund_aum.csv.

Run once by hand (not at chat time) so results are reproducible:
    .venv/Scripts/python data/fetch_fund_aum.py [--upload]
Source: Yahoo Finance via yfinance, Ticker(t).info["totalAssets"] (Yahoo terms of use apply).
A ticker with no AUM is printed and left out; nothing is guessed.
--upload also copies the file to s3://$DATA_BUCKET/data/fund_aum.csv.
"""
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

ETFS = ["XBB.TO", "ZST.TO", "AGG", "TLT", "XIU.TO", "SPY", "QQQ", "ESGV"]
OUT = Path(__file__).resolve().parent / "fund_aum.csv"


def main():
    today = date.today().isoformat()
    rows = []
    for t in ETFS:
        try:
            info = yf.Ticker(t).info
        except Exception as e:
            print(f"{t}: fetch failed ({e}), left out")
            continue
        aum = info.get("totalAssets")
        if not aum:
            print(f"{t}: no totalAssets from Yahoo, left out")
            continue
        ccy = info.get("currency") or ("CAD" if t.endswith(".TO") else "USD")
        rows.append({"ticker": t, "aum": float(aum), "currency": ccy, "aum_date": today,
                     "source": "Yahoo Finance via yfinance (totalAssets)",
                     "source_url": f"https://finance.yahoo.com/quote/{t}", "retrieved_date": today})
        print(f"{t}: {aum:,.0f} {ccy}")
    if not rows:
        sys.exit("no AUM fetched, file not written")
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"wrote {OUT} ({len(rows)}/{len(ETFS)} funds)")
    if "--upload" in sys.argv:
        import boto3
        load_dotenv(OUT.parent.parent / ".env")
        bucket = os.environ["DATA_BUCKET"]
        boto3.client("s3", region_name="us-east-1").upload_file(str(OUT), bucket, "data/fund_aum.csv")
        print(f"uploaded to s3://{bucket}/data/fund_aum.csv")


if __name__ == "__main__":
    main()
