import pytest

from conftest import assert_plain
from personas import PERSONAS
from workers import data_retriever as dr
from workers import risk_analyst as ra
from workers import suitability as su

pytestmark = pytest.mark.skipif(not (dr.DATA_DIR / "prices_daily.csv").exists(), reason="starter data not in data/")


def run(persona, target, w=None):
    r = assert_plain(su.check(persona, target, w))
    assert r["status"] == "ok", r
    return r["data"], {c["rule"]: c for c in r["data"]["checks"]}


# ---------- every limit is evaluated ----------

@pytest.mark.parametrize("persona", sorted(PERSONAS))
@pytest.mark.parametrize("target", ["NVDA", "BTC-USD", "Bonds", "Utilities", "Information Technology", "Gold"])
def test_every_limit_appears(persona, target):
    _, checks = run(persona, target)
    assert set(PERSONAS[persona]["limits"]) <= set(checks)
    assert all(c["status"] in su.SEVERITY and c["explanation"] for c in checks.values())


# ---------- demo questions ----------

def test_robert_nvda_big_position_is_challenged():
    d, c = run("robert", "NVDA", 0.5)
    assert d["overall"] == "conflict"
    assert c["single_stock_max"]["status"] == "conflict" and c["single_stock_max"]["value"] == 0.5
    vol = ra.analyze_asset("NVDA", su.DEFAULT_START, su.DEFAULT_END)["data"]["annualized_vol"]
    assert c["vol_max"]["status"] == "flag" and c["vol_max"]["value"]["NVDA"] == pytest.approx(vol)
    assert c["stress_2022_max_drawdown"]["status"] == "flag"
    assert c["bonds_cash_min"]["status"] == "info"


def test_robert_small_nvda_within_stock_cap():
    _, c = run("robert", "NVDA", 0.05)
    assert c["single_stock_max"]["status"] == "pass"


@pytest.mark.parametrize("persona", ["robert", "mateo"])
def test_crypto_excluded_for_robert_and_mateo(persona):
    d, c = run(persona, "BTC-USD")
    assert c["crypto_max"]["status"] == "conflict" and d["overall"] == "conflict"


@pytest.mark.parametrize("w,status", [(0.10, "pass"), (0.15, "pass"), (0.16, "conflict"), (None, "info")])
def test_amira_crypto_cap(w, status):
    _, c = run("amira", "Crypto asset", w)
    assert c["crypto_max"]["status"] == status


# ---------- caps without a proposed weight are reminders, not flags ----------

@pytest.mark.parametrize("persona,target,rule,cap", [
    ("amira", "Crypto asset", "crypto_max", "15.0%"),
    ("amira", "Information Technology", "sector_max", "50.0%"),
    ("amira", "NVDA", "single_stock_max", "15.0%"),
    ("robert", "NVDA", "single_stock_max", "10.0%"),
    ("robert", "Utilities", "single_stock_max", "10.0%"),  # one-asset industry = single stock
])
def test_unweighted_cap_is_info(persona, target, rule, cap):
    _, c = run(persona, target)
    assert c[rule]["status"] == "info" and c[rule]["value"] is None
    assert f"keep at most {cap}" in c[rule]["explanation"]


def test_amira_tech_without_weight_has_no_flag():
    d, c = run("amira", "Information Technology")
    assert not [r for r, x in c.items() if x["status"] in ("flag", "conflict")]
    assert d["overall"] == "pass"


def test_portfolio_level_limits_still_flag_without_weight():
    d, c = run("robert", "NVDA")  # NVDA alone: vol and 2022 drawdown above Robert's limits
    assert c["vol_max"]["status"] == "flag" and c["stress_2022_max_drawdown"]["status"] == "flag"
    assert c["single_stock_max"]["status"] == "info" and d["overall"] == "flag"


def test_crypto_still_excluded_without_weight():
    _, c = run("robert", "Crypto asset")  # a 0% limit is an exclusion, not a cap
    assert c["crypto_max"]["status"] == "conflict"


@pytest.mark.parametrize("w,status", [(0.5, "pass"), (0.6, "conflict")])
def test_amira_tech_sector_cap(w, status):
    _, c = run("amira", "Information Technology", w)
    assert c["sector_max"]["status"] == status
    assert c["min_asset_classes"]["status"] == "info"  # one asset class on its own


def test_amira_single_tech_stock_hits_sector_and_stock_caps():
    _, c = run("amira", "NVDA", 0.2)
    assert c["single_stock_max"]["status"] == "conflict" and c["sector_max"]["status"] == "pass"


@pytest.mark.parametrize("target,flagged", [("Energy", ["ENB.TO", "CNQ.TO", "XOM"]), ("XOM", ["XOM"]),
                                            ("Utilities", [])])
def test_mateo_esg_review(target, flagged):
    _, c = run("mateo", target)
    assert c["esg_review"]["value"] == flagged
    assert c["esg_review"]["status"] == ("flag" if flagged else "pass")


def test_bonds_count_toward_minimum():
    _, c = run("robert", "Bonds")
    assert c["bonds_cash_min"]["status"] == "pass"
    vols = c["vol_max"]["value"]
    assert set(vols) == {"XBB.TO", "ZST.TO", "AGG", "TLT"}  # building block: members, no blend
    assert "ZST.TO" in c["vol_max"]["explanation"]


def test_numbers_match_risk_analyst():
    _, c = run("mateo", "Energy")
    sec = ra.analyze_sector("Energy", su.DEFAULT_START, su.DEFAULT_END)["data"]
    assert c["vol_max"]["value"]["Energy"] == pytest.approx(sec["annualized_vol"])


# ---------- errors ----------

@pytest.mark.parametrize("args", [("bob", "NVDA"), ("robert", "NOPE"), ("robert", "NVDA", 1.5),
                                  ("robert", "NVDA", -0.1)])
def test_errors_are_dicts(args):
    r = assert_plain(su.check(*args))
    assert r["status"] == "error" and r["error"]


# ---------- regressions from the phase 1-3 review ----------

def test_bonds_minimum_conflicts_with_large_weight():
    _, c = run("mateo", "Utilities", 0.9)       # leaves 10% < 30% bonds
    assert c["bonds_min"]["status"] == "conflict"
    _, c = run("robert", "Broad market", 0.9)   # leaves 10% < 50% bonds/cash
    assert c["bonds_cash_min"]["status"] == "conflict"
    _, c = run("mateo", "Utilities", 0.7)       # leaves exactly 30%
    assert c["bonds_min"]["status"] == "info"


def test_one_asset_industry_is_a_single_stock():
    _, c = run("robert", "Utilities", 0.5)
    assert c["single_stock_max"]["status"] == "conflict" and "FTS.TO" in c["single_stock_max"]["explanation"]


def test_no_2022_stress_before_end_of_2022():
    r = assert_plain(su.check("robert", "NVDA", end="2022-06-30"))
    c = {x["rule"]: x for x in r["data"]["checks"]}
    assert c["stress_2022_max_drawdown"]["status"] == "not_evaluated"
    assert r["period"]["end"] <= "2022-06-30"
    assert not any("251" in w for w in r["warnings"])  # no leak from the 2022 stress window


def test_not_evaluated_is_not_overall_pass():
    r = assert_plain(su.check("mateo", "ZST.TO", start="2030-01-01", end="2030-12-31"))  # nothing else fires
    assert r["data"]["overall"] == "incomplete"
