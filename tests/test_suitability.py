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


@pytest.mark.parametrize("w,status", [(0.10, "pass"), (0.15, "pass"), (0.16, "conflict"), (None, "flag")])
def test_amira_crypto_cap(w, status):
    _, c = run("amira", "Crypto asset", w)
    assert c["crypto_max"]["status"] == status


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
