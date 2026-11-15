"""data_retriever worker: loads prices, FX, macro and asset info from data/ (or S3).

Deterministic, no LLM. Every public function returns a JSON-safe dict:
  {"status": "ok", "data", "source", "period": {"start", "end"}, "currency", "warnings"}
or {"status": "error", "error": "..."}. Functions never raise.
Data is read from local data/ ; if a file is missing locally (or DATA_SOURCE=s3) it is read from
s3://$DATA_BUCKET/data/<file>.
"""
import io
import os
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
load_dotenv(DATA_DIR.parent / ".env")

FX_STALE_DAYS = 5
MACRO_PUBLICATION_LAG_DAYS = 21  # team assumption (CLAUDE.md): monthly data published ~3 weeks after month end
# Per-series overrides, from the FRED series page: RECPROUSM156N's Sep 2026 value was "Updated: Nov 2, 2026"
# (~33 days after month end; retrieved 2026-11-14), so 21 days would use it before it existed.
PUBLICATION_LAG_OVERRIDES = {"RECPROUSM156N": 35}
CURRENCIES = ("CAD", "USD")


# ---------- loading ----------

@lru_cache(maxsize=None)
def _load(name: str) -> pd.DataFrame:
    """Read a CSV from data/ (or S3). Cached. Raises on failure (callers catch)."""
    path = DATA_DIR / name
    if path.exists() and os.getenv("DATA_SOURCE", "local") != "s3":
        df = pd.read_csv(path)
    else:
        import boto3
        bucket = os.environ["DATA_BUCKET"]
        body = boto3.client("s3", region_name="us-east-1").get_object(Bucket=bucket, Key=f"data/{name}")["Body"]
        df = pd.read_csv(io.BytesIO(body.read()))
    for col in ("date", "ex_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    return df


def _source(file: str) -> str:
    try:
        meta = _load("sources_metadata.csv")
        rows = meta[meta["file"] == file]
        parts = [f"{r.source} ({r.source_url}, retrieved {r.retrieved_on})" if isinstance(r.source_url, str)
                 else f"{r.source} (retrieved {r.retrieved_on})" for r in rows.itertuples()]
        return "; ".join(parts) or file
    except Exception:
        return file


# ---------- helpers ----------

def _err(msg: str) -> dict:
    return {"status": "error", "error": msg}


def _ok(data, source, start, end, currency, warnings) -> dict:
    fmt = lambda d: None if d is None or pd.isna(d) else pd.Timestamp(d).strftime("%Y-%m-%d")
    return {"status": "ok", "data": data, "source": source,
            "period": {"start": fmt(start), "end": fmt(end)}, "currency": currency, "warnings": warnings}


def _dates(start, end):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    if s > e:
        raise ValueError(f"start {s.date()} is after end {e.date()}")
    return s, e


def _clean(v):
    """numpy/pandas scalar -> plain Python, NaN -> None."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


def _listing_currency(ticker: str) -> str:
    u = _load("assets_universe.csv")
    return str(u.loc[u["ticker"] == ticker, "currency"].iloc[0])


def _convert(df: pd.DataFrame, value_col: str, from_ccy: str, to_ccy: str, warnings: list, label: str):
    """Convert df[value_col] between USD and CAD using fx_usdcad_daily (backward as-of merge)."""
    if from_ccy == to_ccy:
        return df
    fx = _load("fx_usdcad_daily.csv")[["date", "usdcad"]].sort_values("date").rename(columns={"date": "fx_date"})
    df = df.sort_values("date")
    m = pd.merge_asof(df, fx, left_on="date", right_on="fx_date", direction="backward")
    if m["usdcad"].isna().any():
        warnings.append(f"{label}: {int(m['usdcad'].isna().sum())} rows before first FX date dropped")
        m = m.dropna(subset=["usdcad"])
    stale = (m["date"] - m["fx_date"]).dt.days > FX_STALE_DAYS
    if stale.any():
        warnings.append(f"{label}: {int(stale.sum())} rows use an FX rate more than {FX_STALE_DAYS} days old")
    m[value_col] = m[value_col] * m["usdcad"] if to_ccy == "CAD" else m[value_col] / m["usdcad"]
    return m.drop(columns=["usdcad", "fx_date"])


# ---------- public functions ----------

def get_universe() -> dict:
    """List the 31 assets in the analysis universe (ticker, name, asset_class, market, currency, sector)."""
    try:
        u = _load("assets_universe.csv")
        return _ok([{k: _clean(v) for k, v in r.items()} for r in u.to_dict("records")],
                   _source("assets_universe.csv"), None, None, None, [])
    except Exception as e:
        return _err(f"could not load universe: {e}")


def get_asset_info(ticker: str) -> dict:
    """Return the universe row for one ticker."""
    try:
        u = _load("assets_universe.csv")
        row = u[u["ticker"] == ticker]
        if row.empty:
            return _err(f"unknown ticker '{ticker}' (not in assets_universe.csv)")
        return _ok({k: _clean(v) for k, v in row.iloc[0].to_dict().items()},
                   _source("assets_universe.csv"), None, None, None, [])
    except Exception as e:
        return _err(f"could not load asset info: {e}")


def get_prices(tickers, start: str, end: str, currency: str = "CAD") -> dict:
    """Daily adj_close per ticker between start and end (inclusive), converted to `currency` (CAD or USD).

    data = {ticker: [{"date": "YYYY-MM-DD", "adj_close": float}, ...]}. No forward-fill, no calendar alignment.
    """
    try:
        if isinstance(tickers, str):
            tickers = [tickers]
        tickers = list(dict.fromkeys(tickers))
        if not tickers:
            return _err("no tickers given")
        if currency not in CURRENCIES:
            return _err(f"currency must be one of {CURRENCIES}")
        s, e = _dates(start, end)
        prices = _load("prices_daily.csv")
        known = set(_load("assets_universe.csv")["ticker"])
        data, warnings, dmin, dmax = {}, [], None, None
        dropped_after = False
        for t in tickers:
            if t not in known:
                warnings.append(f"unknown ticker '{t}' (not in assets_universe.csv)")
                continue
            df = prices.loc[(prices["ticker"] == t) & (prices["date"] >= s) & (prices["date"] <= e),
                            ["date", "adj_close"]]
            if ((prices["ticker"] == t) & (prices["date"] > e)).any():
                dropped_after = True
            if df.empty:
                warnings.append(f"{t}: no prices between {s.date()} and {e.date()}")
                continue
            df = _convert(df, "adj_close", _listing_currency(t), currency, warnings, t)
            data[t] = [{"date": d.strftime("%Y-%m-%d"), "adj_close": float(v)}
                       for d, v in zip(df["date"], df["adj_close"])]
            dmin = df["date"].min() if dmin is None else min(dmin, df["date"].min())
            dmax = df["date"].max() if dmax is None else max(dmax, df["date"].max())
        if not data:
            return _err("; ".join(warnings) or "no data")
        if dropped_after:  # guardrails/03_workers_contract.md: look-ahead rows are reported, not hidden.
            # No row count: it would change when newer data is appended, and results must not (no look-ahead).
            warnings.append(f"rows dated after the end date {e.date()} were excluded (no look-ahead)")
        return _ok(data, _source("prices_daily.csv") + "; FX: " + _source("fx_usdcad_daily.csv"),
                   dmin, dmax, currency, warnings)
    except Exception as e:
        return _err(f"get_prices failed: {e}")


def get_fx(start: str, end: str) -> dict:
    """USD/CAD rates (usdcad = CAD per 1 USD) between start and end."""
    try:
        s, e = _dates(start, end)
        fx = _load("fx_usdcad_daily.csv")
        fx = fx[(fx["date"] >= s) & (fx["date"] <= e)]
        if fx.empty:
            return _err(f"no FX rows between {s.date()} and {e.date()}")
        data = [{"date": d.strftime("%Y-%m-%d"), "usdcad": float(u), "cadusd": float(c)}
                for d, u, c in zip(fx["date"], fx["usdcad"], fx["cadusd"])]
        return _ok(data, _source("fx_usdcad_daily.csv"), fx["date"].min(), fx["date"].max(), None, [])
    except Exception as e:
        return _err(f"get_fx failed: {e}")


def get_macro(series_ids, start: str, end: str, as_of: str | None = None) -> dict:
    """Macro series values between start and end that were PUBLISHED by `as_of` (default: end).

    Monthly series are dated to the reference month; they count as published MACRO_PUBLICATION_LAG_DAYS
    after the end of that month (team assumption). data = {series_id: [{"date", "available_date", "value"}]}.
    """
    try:
        if isinstance(series_ids, str):
            series_ids = [series_ids]
        s, e = _dates(start, end)
        cutoff = pd.Timestamp(as_of) if as_of else e
        frames = [_load("macro_rates.csv")]
        if (DATA_DIR / "macro_extra.csv").exists() or os.getenv("DATA_SOURCE") == "s3":
            frames.append(_load("macro_extra.csv"))
        macro = pd.concat(frames, ignore_index=True)
        data, warnings, sources, units = {}, [], set(), {}
        for sid in series_ids:
            df = macro[macro["series_id"] == sid].copy()
            if df.empty:
                warnings.append(f"unknown series '{sid}'")
                continue
            monthly = df["frequency"].str.contains("monthly", case=False)
            df["available_date"] = df["date"]
            lag = PUBLICATION_LAG_OVERRIDES.get(sid, MACRO_PUBLICATION_LAG_DAYS)
            df.loc[monthly, "available_date"] = (df.loc[monthly, "date"] + pd.offsets.MonthEnd(0)
                                                 + pd.Timedelta(days=lag))
            df = df[(df["date"] >= s) & (df["date"] <= e) & (df["available_date"] <= cutoff)]
            if df.empty:
                warnings.append(f"{sid}: no values published by {cutoff.date()} in range")
                continue
            if monthly.any():
                warnings.append(f"{sid}: monthly, assumed published {lag} days after month end")
            sources.update(df["source"].unique())
            units[sid] = str(df["unit"].iloc[0])
            data[sid] = [{"date": d.strftime("%Y-%m-%d"), "available_date": a.strftime("%Y-%m-%d"), "value": _clean(v)}
                         for d, a, v in zip(df["date"], df["available_date"], df["value"])]
        if not data:
            return _err("; ".join(warnings) or "no data")
        all_dates = [r["date"] for rows in data.values() for r in rows]
        res = _ok(data, "; ".join(sorted(sources)), min(all_dates), max(all_dates), None, warnings)
        res["units"] = units
        return res
    except Exception as e:
        return _err(f"get_macro failed: {e}")
