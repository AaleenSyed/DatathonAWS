"""Fetch company fundamentals and profiles for the AlphaForge universe.

Sources
- SEC EDGAR XBRL "companyfacts" API (official filings, free, no key). Covers U.S. companies
  (10-K, US GAAP) and Canadian companies that file with the SEC (40-F, usually IFRS).
  Each value keeps the date it was FIRST filed, so a simulation can avoid using data
  before it was public.
- yfinance (Yahoo Finance) as a fallback for companies not registered with the SEC
  (e.g. ATD.TO, CSU.TO). Yahoo has no filing date, so publication is ESTIMATED as
  fiscal period end + 90 days and flagged.
- yfinance .info for a current company/ETF profile snapshot (sector, beta, fees...).
  This is a snapshot as of the retrieval date, NOT point-in-time.

Usage (Kiro terminal, CloudShell, or laptop with internet):
    pip install pandas requests yfinance
    python fetch_fundamentals.py --email you@example.com

Outputs (in data/):
    fundamentals.csv      long format: ticker, metric, fiscal_period_end, value, unit,
                          publication_date, publication_date_estimated, form, source, ...
    company_profiles.csv  one row per asset, current snapshot
    fundamentals_coverage.txt  which metrics/years were found per ticker
"""

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent / "data"
TODAY = date.today().isoformat()
YEARS_TO_KEEP = 6
ANNUAL_FORMS = {"10-K", "40-F", "20-F"}

# Yahoo ticker -> SEC ticker, when they differ (CN Rail trades as CNI in New York)
EDGAR_SYMBOL_OVERRIDES = {"CNR.TO": "CNI"}

# metric -> ordered list of (taxonomy, concept). First match wins per fiscal period.
# kind: "duration" = flow over the fiscal year (income, cash flow); "instant" = balance sheet date.
CONCEPTS = {
    "revenue": ("duration", [
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "Revenues"),
        ("us-gaap", "SalesRevenueNet"),
        ("ifrs-full", "Revenue"),
        ("ifrs-full", "RevenueFromContractsWithCustomers"),
    ]),
    "net_income": ("duration", [
        ("us-gaap", "NetIncomeLoss"),
        ("ifrs-full", "ProfitLossAttributableToOwnersOfParent"),
        ("ifrs-full", "ProfitLoss"),
    ]),
    "eps_diluted": ("duration", [
        ("us-gaap", "EarningsPerShareDiluted"),
        ("ifrs-full", "DilutedEarningsLossPerShare"),
    ]),
    "operating_cash_flow": ("duration", [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
    ]),
    "total_assets": ("instant", [
        ("us-gaap", "Assets"),
        ("ifrs-full", "Assets"),
    ]),
    "total_liabilities": ("instant", [
        ("us-gaap", "Liabilities"),
        ("ifrs-full", "Liabilities"),
    ]),
    "shareholders_equity": ("instant", [
        ("us-gaap", "StockholdersEquity"),
        ("ifrs-full", "EquityAttributableToOwnersOfParent"),
        ("ifrs-full", "Equity"),
    ]),
    "cash": ("instant", [
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
        ("ifrs-full", "CashAndCashEquivalents"),
    ]),
    "long_term_debt": ("instant", [
        ("us-gaap", "LongTermDebtNoncurrent"),
        ("us-gaap", "LongTermDebt"),
        ("ifrs-full", "NoncurrentPortionOfNoncurrentBorrowings"),
        ("ifrs-full", "LongtermBorrowings"),
    ]),
}

# yfinance row labels for the fallback (first label found wins)
YF_ROWS = {
    "revenue": ("income_stmt", ["Total Revenue", "Operating Revenue"]),
    "net_income": ("income_stmt", ["Net Income", "Net Income Common Stockholders"]),
    "eps_diluted": ("income_stmt", ["Diluted EPS"]),
    "operating_cash_flow": ("cashflow", ["Operating Cash Flow"]),
    "total_assets": ("balance_sheet", ["Total Assets"]),
    "total_liabilities": ("balance_sheet", ["Total Liabilities Net Minority Interest"]),
    "shareholders_equity": ("balance_sheet", ["Stockholders Equity", "Common Stock Equity"]),
    "cash": ("balance_sheet", ["Cash And Cash Equivalents"]),
    "long_term_debt": ("balance_sheet", ["Long Term Debt"]),
}

PROFILE_FIELDS = [
    "longName", "quoteType", "sector", "industry", "country", "financialCurrency",
    "marketCap", "beta", "trailingPE", "dividendYield", "fullTimeEmployees",
    "category", "totalAssets", "netExpenseRatio", "fundFamily",
]


# ---------------------------------------------------------------- EDGAR

def sec_get(url: str, headers: dict) -> requests.Response:
    time.sleep(0.15)  # SEC limit is 10 requests/second
    return requests.get(url, headers=headers, timeout=30)


def load_cik_map(headers: dict) -> dict:
    r = sec_get("https://www.sec.gov/files/company_tickers.json", headers)
    r.raise_for_status()
    return {row["ticker"].upper(): int(row["cik_str"]) for row in r.json().values()}


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def parse_companyfacts(facts: dict, ticker: str, cik: int) -> list[dict]:
    """Turn a companyfacts JSON into annual, first-published values per metric."""
    source_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    rows = []
    for metric, (kind, candidates) in CONCEPTS.items():
        best: dict[str, dict] = {}  # fiscal_period_end -> chosen record
        for priority, (taxonomy, concept) in enumerate(candidates):
            node = facts.get("facts", {}).get(taxonomy, {}).get(concept)
            if not node:
                continue
            for unit, entries in node.get("units", {}).items():
                for f in entries:
                    if f.get("form") not in ANNUAL_FORMS:
                        continue
                    end = f.get("end")
                    if not end or "filed" not in f:
                        continue
                    if kind == "duration":
                        if "start" not in f or not (350 <= _days(f["start"], end) <= 380):
                            continue
                    elif f.get("fp") not in (None, "FY"):
                        continue
                    rec = {
                        "ticker": ticker, "metric": metric, "fiscal_period_end": end,
                        "value": f["val"], "unit": unit,
                        "publication_date": f["filed"], "publication_date_estimated": False,
                        "form": f["form"], "accession": f.get("accn", ""),
                        "concept": f"{taxonomy}:{concept}", "_priority": priority,
                        "source": "SEC EDGAR XBRL companyfacts", "source_url": source_url,
                        "retrieved_on": TODAY,
                    }
                    cur = best.get(end)
                    # prefer higher-priority concept, then the FIRST filing (point-in-time)
                    if cur is None or (priority, f["filed"]) < (cur["_priority"], cur["publication_date"]):
                        best[end] = rec
        for end in sorted(best)[-YEARS_TO_KEEP:]:
            rec = best[end]
            rec.pop("_priority")
            rows.append(rec)
    return rows


def fetch_edgar(ticker: str, cik_map: dict, headers: dict) -> list[dict]:
    symbol = EDGAR_SYMBOL_OVERRIDES.get(ticker, ticker.replace(".TO", "")).upper()
    cik = cik_map.get(symbol)
    if cik is None:
        return []
    r = sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", headers)
    if r.status_code != 200:
        return []
    return parse_companyfacts(r.json(), ticker, cik)


# ---------------------------------------------------------------- yfinance fallback

def fetch_yfinance(ticker: str) -> list[dict]:
    import yfinance as yf

    t = yf.Ticker(ticker)
    try:
        currency = (t.info or {}).get("financialCurrency", "")
    except Exception:
        currency = ""
    tables = {}
    rows = []
    for metric, (table_name, labels) in YF_ROWS.items():
        if table_name not in tables:
            try:
                tables[table_name] = getattr(t, table_name)
            except Exception:
                tables[table_name] = pd.DataFrame()
        df = tables[table_name]
        if df is None or df.empty:
            continue
        label = next((lbl for lbl in labels if lbl in df.index), None)
        if label is None:
            continue
        for period_end, val in df.loc[label].dropna().items():
            end = pd.Timestamp(period_end).date()
            rows.append({
                "ticker": ticker, "metric": metric, "fiscal_period_end": end.isoformat(),
                "value": float(val), "unit": currency or "unknown",
                "publication_date": (end + timedelta(days=90)).isoformat(),
                "publication_date_estimated": True,
                "form": "annual statement (Yahoo)", "accession": "",
                "concept": f"yfinance:{label}",
                "source": "Yahoo Finance via yfinance", "source_url": f"https://finance.yahoo.com/quote/{ticker}/financials",
                "retrieved_on": TODAY,
            })
    return rows


def fetch_profiles(tickers: list[str]) -> pd.DataFrame:
    import yfinance as yf

    out = []
    for tk in tickers:
        row = {"ticker": tk, "snapshot_date": TODAY, "source": "Yahoo Finance via yfinance (current snapshot, not point-in-time)"}
        try:
            info = yf.Ticker(tk).info or {}
            row.update({k: info.get(k) for k in PROFILE_FIELDS})
            summary = info.get("longBusinessSummary") or ""
            row["business_summary"] = summary[:600]
        except Exception as e:
            row["error"] = str(e)[:200]
        out.append(row)
        time.sleep(0.3)
    return pd.DataFrame(out)


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True, help="Contact email for the SEC User-Agent (required by SEC)")
    ap.add_argument("--skip-profiles", action="store_true")
    args = ap.parse_args()

    universe = pd.read_csv(DATA_DIR / "assets_universe.csv")
    equities = universe.loc[universe["asset_class"] == "equity", "ticker"].tolist()
    headers = {"User-Agent": f"PolyFinances Datathon AlphaForge {args.email}"}

    print("Loading SEC ticker -> CIK map...")
    cik_map = load_cik_map(headers)

    all_rows, coverage = [], []
    for tk in equities:
        rows = fetch_edgar(tk, cik_map, headers)
        src = "EDGAR"
        if not rows:
            rows = fetch_yfinance(tk)
            src = "yfinance (estimated pub. dates)" if rows else "NONE"
        all_rows.extend(rows)
        found = sorted({r["metric"] for r in rows})
        years = sorted({r["fiscal_period_end"][:4] for r in rows})
        missing = sorted(set(CONCEPTS) - set(found))
        line = f"{tk:8} {src:32} years={','.join(years) or '-':30} missing={','.join(missing) or 'none'}"
        coverage.append(line)
        print(line)

    fund = pd.DataFrame(all_rows).sort_values(["ticker", "metric", "fiscal_period_end"])
    fund.to_csv(DATA_DIR / "fundamentals.csv", index=False)
    (DATA_DIR / "fundamentals_coverage.txt").write_text(
        f"Generated {TODAY}\n" + "\n".join(coverage) + "\n")
    print(f"\nWrote {len(fund)} rows to data/fundamentals.csv")

    if not args.skip_profiles:
        print("Fetching profiles (equities + ETFs + crypto)...")
        prof = fetch_profiles(universe["ticker"].tolist())
        prof.to_csv(DATA_DIR / "company_profiles.csv", index=False)
        print(f"Wrote {len(prof)} rows to data/company_profiles.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
