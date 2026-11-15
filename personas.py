"""Fictional investor personas (from the PolyFinances Datathon 2026 brief).

Profiles are fictional. Numeric limits are TEAM ASSUMPTIONS (see CLAUDE.md / README), not part of the brief.
Fractions: 0.15 = 15%.
"""

PERSONAS = {
    "amira": {
        "name": "Amira",
        "age": 26,
        "occupation": "Software engineer",
        "risk_tolerance": "high",
        "horizon_years": "15+",
        "goal": "Long-term growth",
        "preferences": ["AI", "emerging tech", "crypto", "still wants diversification, not 100% tech"],
        "limits": {
            "crypto_max": 0.15,
            "single_stock_max": 0.15,
            "sector_max": {"Information Technology": 0.50},
            "min_asset_classes": 3,
        },
        "esg_review_tickers": [],
    },
    "mateo": {
        "name": "Mateo",
        "age": 41,
        "occupation": "Operations manager, partner + 2 kids",
        "risk_tolerance": "moderate",
        "horizon_years": "8-12",
        "goal": "Balanced growth",
        "preferences": ["strong ESG preference",
                        "avoid companies with significant environmental/social controversies",
                        "little interest in speculative assets"],
        "limits": {
            "crypto_max": 0.0,
            "vol_max": 0.15,
            "bonds_min": 0.30,
        },
        "esg_review_tickers": ["ENB.TO", "CNQ.TO", "XOM"],
    },
    "robert": {
        "name": "Robert",
        "age": 59,
        "occupation": "Healthcare professional, near retirement",
        "risk_tolerance": "low-moderate",
        "horizon_years": "3-5",
        "goal": "Capital preservation with some growth",
        "preferences": ["established companies", "little interest in crypto",
                        "may be tempted by a hyped stock (e.g. NVDA, TSLA)"],
        "limits": {
            "crypto_max": 0.0,
            "single_stock_max": 0.10,
            "vol_max": 0.10,
            "bonds_cash_min": 0.50,
            "stress_2022_max_drawdown": -0.15,  # max drawdown in 2022 must not be worse than -15%
        },
        "esg_review_tickers": [],
    },
}

SOURCE = "PolyFinances Datathon 2026 brief (profiles); numeric limits are team assumptions"


def get_persona(name: str) -> dict:
    """Return a persona dict by name (case-insensitive), or an error dict."""
    p = PERSONAS.get(str(name).strip().lower())
    if p is None:
        return {"status": "error", "error": f"unknown persona '{name}'; choose one of {sorted(PERSONAS)}"}
    return {"status": "ok", "data": p, "source": SOURCE, "period": None, "currency": None, "warnings": []}
