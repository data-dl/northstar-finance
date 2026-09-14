"""End to end: the real pipeline over the generated sample must load, reconcile, pass every
integrity check and render, and the headline numbers must hang together."""
import json
import pathlib
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finlib import loaders, metrics as metrics_lib, reconcile as rc, validate   # noqa: E402
from synth.generate import generate                                            # noqa: E402


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    data = tmp_path_factory.mktemp("sample") / "data"
    generate(data)
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    loaded = {
        "bank": loaders.load_bank(data, config),
        "cards": loaders.load_cards(data, config["cards"]),
        "amazon": loaders.load_amazon(data),
        "venmo": loaders.load_venmo(data, config["identity"]["venmo_name"]),
        "balances": loaders.load_balances(data),
        "holdings": loaders.load_vanguard_holdings(data),
        "chewy": loaders.load_chewy(data),
        "card_statements": loaders.load_card_statements(data, config["cards"]),
        "card_alerts": loaders.load_card_alerts(data),
        "alert_review": loaders.load_alert_review(data),
        "statement_balances": loaders.load_statement_balances(data),
    }
    m = metrics_lib.compute_metrics(loaded, config)
    checks = validate.run_checks(loaded, config, m)
    return config, loaded, m, checks


def test_every_integrity_check_passes(built):
    _, _, _, checks = built
    failed = [c["name"] for c in checks if not c["passed"] and c["critical"]]
    assert not failed, failed
    assert len(checks) == 20


def test_overlapping_exports_do_not_double_count(built):
    """Two bank files overlap on Nov-Dec 2025 and two Freedom pulls overlap on Jul 2024-Aug 1
    2026; rent must still land exactly once a month."""
    _, loaded, _, _ = built
    bank = rc.reconcile_bank(loaded["bank"], built[0])
    rent = bank[bank["Description"].str.contains("Havenbrook|Old Rent Portal")]
    per_month = rent.groupby("month").size()
    assert per_month.max() == 1 and len(per_month) == 26


def test_card_payments_are_not_spending(built):
    config, loaded, _, _ = built
    bank = rc.reconcile_bank(loaded["bank"], config)
    autopay = bank[bank["Description"] == "Chase Credit Card"]
    assert len(autopay) > 20
    assert set(autopay["bucket"]) == {rc.BUCKET_CARD_PAYMENT}


def test_lending_is_a_balance_sheet_move(built):
    config, loaded, m, _ = built
    bank = rc.reconcile_bank(loaded["bank"], config)
    loan = bank[bank["Description"].str.contains("Alex Carver")]
    assert len(loan) == 1 and loan.iloc[0]["bucket"] == rc.BUCKET_LOAN_OUT
    assert m["net_worth_detail"]["by_tax"]["receivable"] == 3500.0
    assert m["runway_inputs"]["cash_hysa"] == m["net_worth_detail"]["by_tax"]["cash"]


def test_savings_rate_is_plausible(built):
    _, _, m, _ = built
    s = m["summary"]
    assert 20 <= s["savings_rate_takehome"] <= 45
    assert 2400 <= s["avg_spend_mo"] <= 3400
    assert s["net_worth"] == m["net_worth_detail"]["net_total"]


def test_venmo_transfers_are_relabelled_not_added(built):
    """The bank's 'Transfer to Venmo' rows are split across what the Venmo statement says
    they bought; the total must be conserved."""
    config, loaded, m, _ = built
    bank = rc.reconcile_bank(loaded["bank"], config)
    transfers = float(bank[bank["Description"] == "Transfer to Venmo"]["Amount"].sum())
    split_names = set(config["venmo_category_split"].values())
    split_total = sum(mm["total"] for c in m["categories"] for mm in c["merchants"] if mm["name"] in split_names)
    leftover = next((c["avg_mo"] for c in m["categories"] if c["key"] == "venmo"), 0.0) * m["_internal"]["n_avg_months"]
    assert abs(transfers - split_total - leftover) < 1.0


def test_alerts_stay_in_the_pending_lane(built):
    _, loaded, m, _ = built
    a = m["card_alerts"]
    assert a["count"] == len(loaded["card_alerts"]) and a["superseded"] == 0
    assert a["credits"] == 24.99 and a["net"] == round(a["spend"] - a["credits"], 2)
    assert a["since"] > m["coverage"]["cards"]["end"]                       # every alert is newer than the export
    statuses = {c["name"]: c["status"] for c in a["cards"]}
    assert statuses["Discover it (Capital One)"] == "no_alerts"


def test_corner_store_decoder_reads_the_baskets(built):
    _, _, m, _ = built
    d = m["deli_decode"]
    assert d["merchant"] == "Fourth Street Market" and d["on_grid_pct"] > 80 and d["explained_pct"] > 70
    assert d["combo"]["charged"] == 5.35 and d["combo"]["count"] > 100
    assert m["energy"]["deli_per_can"] == 3.48 and m["energy"]["bulk_per_can"] == 1.75


def test_price_creep_and_ended_services_are_detected(built):
    _, _, m, _ = built
    by_name = {r["name"].lower(): r for r in m["recurring"]}
    assert by_name["netflix"]["price_change"] and by_name["netflix"]["price_change"]["to"] == 17.99
    assert by_name["vantel"]["price_change"]["from"] == 45.0
    assert not by_name["hulu"]["active"] and not by_name["old rent portal"]["active"]
    assert by_name["havenbrook"]["active"] and by_name["havenbrook"]["cadence"] == "monthly"


def test_update_py_renders_all_four_pages(tmp_path):
    data, out = tmp_path / "data", tmp_path / "out"
    generate(data)
    r = subprocess.run([sys.executable, str(ROOT / "update.py"), "--data", str(data), "--output", str(out)],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Validation passed (20/20 checks)" in r.stdout
    for name in ("index.html", "dashboard.html", "portfolio_gauge.html", "runway.html"):
        assert (out / name).exists()
    payload = json.loads((out / "data.js").read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";"))
    assert payload["validation"]["all_passed"]


def test_clock_is_pinned_for_the_sample_and_free_for_real_data(built):
    """The sample's freshness check must not depend on the day the build runs."""
    import pandas as pd
    config, loaded, m, checks = built
    assert config["clock"] == pd.Timestamp("2026-09-12").date()
    fresh = next(c for c in checks if c["name"].startswith("Data freshness"))
    assert fresh["passed"] and "11 days ago" in fresh["detail"]
    assert m["data_quality"]["stale_days"] == 11
    # unpinned: the wall clock, and a 2026 dataset reads as stale without failing the build
    free = dict(config); free.pop("clock")
    assert abs((metrics_lib.today(free) - pd.Timestamp.now()).total_seconds()) < 5
    later = dict(config); later["clock"] = "2027-01-01"
    stale = validate.run_checks(loaded, later, metrics_lib.compute_metrics(loaded, later))
    fresh = next(c for c in stale if c["name"].startswith("Data freshness"))
    assert not fresh["passed"] and not fresh["critical"]
