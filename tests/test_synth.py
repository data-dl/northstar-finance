"""The generator's contract: same seed, same bytes; every file the loaders read is present and
parses; the numbers the templates' commentary quotes are actually in the data."""
import csv
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from synth import persona as P            # noqa: E402
from synth.generate import generate       # noqa: E402

EXPECTED_FILES = [
    "bank/transactions_2024-07-01_2025-12-31.csv", "bank/transactions_2025-11-01_2026-08-31.csv",
    "cards/Chase4417_Activity_20260801.csv", "cards/Chase4417_Activity_20260901.csv",
    "cards/Chase8802_Activity_20260901.csv", "cards/statements.json",
    "amazon/amazon_order_history_2025.csv", "amazon/amazon_order_history_2026.csv",
    "venmo/VenmoStatement_Jan_Dec_2015.csv", "venmo/VenmoStatement_Jan_Dec_2026.csv",
    "chewy/chewy_orders_2026.csv",
    "balances/balances.csv", "balances/credit_cards.csv", "balances/VANGUARD_ACCOUNT_LIST.csv",
    "alerts/alerts.csv", "alerts/review.json", "alerts/statement-balances.json", "alerts/not-spending.json",
    "MANIFEST.json",
]


def _digest(folder: pathlib.Path) -> dict:
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def test_every_expected_file_is_written(tmp_path):
    generate(tmp_path / "d")
    missing = [f for f in EXPECTED_FILES if not (tmp_path / "d" / f).exists()]
    assert not missing, missing


def test_same_seed_same_bytes(tmp_path):
    generate(tmp_path / "a", seed=20260912)
    generate(tmp_path / "b", seed=20260912)
    assert _digest(tmp_path / "a") == _digest(tmp_path / "b")


def test_different_seed_different_transactions(tmp_path):
    generate(tmp_path / "a", seed=1)
    generate(tmp_path / "b", seed=2)
    a = (tmp_path / "a" / "bank/transactions_2025-11-01_2026-08-31.csv").read_bytes()
    b = (tmp_path / "b" / "bank/transactions_2025-11-01_2026-08-31.csv").read_bytes()
    assert a != b


def test_committed_sample_matches_generator():
    """data/ in the repository is exactly what `python -m synth` writes."""
    import tempfile
    repo = pathlib.Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        generate(pathlib.Path(tmp) / "d")
        fresh = _digest(pathlib.Path(tmp) / "d")
    committed = _digest(repo / "data")
    assert fresh == committed, "data/ is stale: run `python -m synth --out data`"


def test_bank_export_shape(tmp_path):
    generate(tmp_path / "d")
    with (tmp_path / "d" / "bank/transactions_2025-11-01_2026-08-31.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0].keys() >= {"Date", "Description", "Original Description", "Amount", "Type", "Parent Category", "Account"}
    assert {r["Type"] for r in rows} == {"Debit", "Credit"}
    assert all(float(r["Amount"]) > 0 for r in rows), "the credit union's export never signs Amount; Type carries direction"
    assert {r["Account"] for r in rows} == {"FREE CHECKING", "SHARE SAVINGS"}
    payroll = [r for r in rows if r["Description"] == P.PAYROLL_DESC]
    assert payroll and all(r["Parent Category"] == "Income" and float(r["Amount"]) == P.PAY_NET for r in payroll)


def test_card_export_signs_like_chase(tmp_path):
    generate(tmp_path / "d")
    with (tmp_path / "d" / "cards/Chase4417_Activity_20260901.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    sales = [r for r in rows if r["Type"] == "Sale"]
    payments = [r for r in rows if r["Type"] == "Payment"]
    assert sales and all(float(r["Amount"]) < 0 for r in sales)
    assert payments and all(float(r["Amount"]) > 0 for r in payments)
    assert any(r["Type"] == "Return" for r in rows)


def test_venmo_statement_has_the_real_layout(tmp_path):
    generate(tmp_path / "d")
    lines = (tmp_path / "d" / "venmo/VenmoStatement_Jan_Dec_2026.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("Account Statement - (")
    assert lines[2].startswith(",ID,Datetime,Type,Status,Note,From,To,Amount (total)")
    assert "$" in lines[3] and lines[3].startswith(",,,,")       # the beginning-balance row
    assert any(",Standard Transfer," not in ln and ",Payment," in ln for ln in lines[4:])


def test_statement_points_reconcile(tmp_path):
    generate(tmp_path / "d")
    for st in json.loads((tmp_path / "d" / "cards/statements.json").read_text(encoding="utf-8")):
        p = st["points"]
        assert p["previous"] + sum(e["points"] for e in p["earn_lines"]) - p["redeemed"] == p["total"]


def test_corner_store_tickets_sit_on_the_price_grid(tmp_path):
    """The Corner Stores tab reads tickets back into baskets because they land on a
    $0.25 grid plus 7% tax. The generator must honour that, or the decoder has nothing
    to decode."""
    generate(tmp_path / "d")
    unit = 0.25 * (1 + P.DELI_TAX)
    tickets = []
    for name in ("cards/Chase4417_Activity_20260901.csv", "cards/Chase4417_Activity_20260801.csv"):
        with (tmp_path / "d" / name).open(encoding="utf-8", newline="") as fh:
            tickets += [-float(r["Amount"]) for r in csv.DictReader(fh) if r["Description"] == P.DELI and r["Type"] == "Sale"]
    assert len(tickets) > 100
    on_grid = sum(1 for t in tickets if abs(round(t / unit) - t / unit) < 0.01)
    assert on_grid / len(tickets) > 0.8
    signature = round(sum(P.DELI_ITEMS[i] for i in ("Red Bull", "Clif Bar")) * (1 + P.DELI_TAX), 2)
    assert sum(1 for t in tickets if abs(t - signature) < 0.005) / len(tickets) > 0.3


def test_vanguard_export_parses_with_the_real_loader(tmp_path):
    from finlib import loaders
    generate(tmp_path / "d")
    df = loaders.load_vanguard_holdings(tmp_path / "d")
    assert set(df["account_number"].str[-4:]) == {a[-4:] for a in P.VANGUARD}
    assert (df["shares"] * df["price"] - df["value"]).abs().max() < 0.01
