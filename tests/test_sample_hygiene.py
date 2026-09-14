"""The sample must describe the sample household and nothing else.

Every account, card, counterparty and merchant in data/, config.yaml and the templates' hand
written commentary has to come from synth/persona.py. These checks cannot prove a stray real
detail is absent, but they do prove the generated files are closed over the invented vocabulary,
and that the prose in the templates quotes figures the data actually contains."""
import csv
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from synth import persona as P   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SAMPLE_CARDS = {"4417", "8802", "3160"}
SAMPLE_PEOPLE = {P.OWNER, P.SETTLED_LOAN, P.FRUIT_VENDOR, P.MOVIE_BUDDY, P.EVENT_FRIEND, P.LOAN_BORROWER,
                 *P.MEAL_FRIENDS, *(name for name, *_ in P.RENT_ROOMMATES)}


def _csv(path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def test_only_sample_cards_appear_anywhere():
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in list(DATA.rglob("*")) + [ROOT / "config.yaml"] if p.is_file())
    for cid in re.findall(r"Chase(\d{4})|card_id[\"']?[:,]\s*[\"']?(\d{4})|\.\.\.(\d{4})|x(\d{4})\b", text):
        found = next(c for c in cid if c)
        if found in {"3142", "8827", "5510", "0417", "4471", "2290"}:   # account suffixes, not cards
            continue
        assert found in SAMPLE_CARDS, found


def test_venmo_counterparties_are_all_invented():
    seen = set()
    for path in (DATA / "venmo").glob("*.csv"):
        for r in _csv(path)[1:]:        # skip the beginning-balance row
            if r.get("Datetime"):
                seen.update({r["From"], r["To"]})
    seen.discard("")
    assert seen <= SAMPLE_PEOPLE, seen - SAMPLE_PEOPLE


def test_card_merchants_come_from_the_persona_vocabulary():
    vocab = {P.DELI, "CHEWY.COM", "AUTOMATIC PAYMENT - THANK"}
    vocab |= {d for d, *_ in P.SNACK_STORES + P.RESTAURANTS + P.GROCERS + P.DRUGSTORES + P.ENTERTAINMENT}
    vocab |= {P.TRANSIT_TAP[0], P.PARKING[0], P.TARGET[0]}
    vocab |= {d for d, *_ in P.SUBSCRIPTIONS + P.ANNUALS + P.CARD_RETURNS}
    for path in (DATA / "cards").glob("*.csv"):
        for r in _csv(path):
            d = r["Description"]
            if d.startswith(("AMAZON MKTPL*", "LYFT *RIDE")):
                continue
            assert d in vocab, d


def test_balances_name_only_sample_institutions():
    rows = _csv(DATA / "balances" / "balances.csv")
    assert {r["institution"] for r in rows} == {"Vanguard", "Voya", "State Retirement System", "Lakeshore Credit Union", "Fidelity", "Personal"}
    # the gauge finds accounts by these substrings; drop one and a balance silently vanishes
    names = " | ".join(r["account"] for r in rows)
    for needle in ("Credit Union", "403b", "Prior-state", "Fidelity"):
        assert needle in names, needle


def test_no_email_addresses_outside_the_issuer_allow_list():
    from finlib.alerts import ISSUERS
    allowed = {s for i in ISSUERS for s in i.senders} | {"no.reply.alerts@chase.com"}
    for path in [p for p in ROOT.rglob("*") if p.is_file() and p.suffix in {".py", ".yaml", ".csv", ".json", ".html", ".md"}
                 and not any(part in {".git", ".venv", "output", "__pycache__", ".pytest_cache"} for part in p.parts)]:
        for addr in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", path.read_text(encoding="utf-8", errors="replace")):
            placeholder = addr.endswith(("example", ".example.com", "users.noreply.github.com")) or addr.split("@")[1] in {"x.com", "y.com"}
            assert addr in allowed or placeholder, (path, addr)


def test_commentary_quotes_the_sample_numbers():
    """The templates carry hand-written sentences calibrated to this dataset. If the persona
    moves, these must move with it, so the pinned figures are asserted here."""
    dash = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
    gauge = (ROOT / "templates" / "portfolio_gauge.html").read_text(encoding="utf-8")
    runway = (ROOT / "templates" / "runway.html").read_text(encoding="utf-8")
    assert f"${P.DELI_ITEMS['Red Bull']:.2f} Red Bull and ${P.DELI_ITEMS['Clif Bar']:.2f} Clif Bar" in dash
    assert "Chase Freedom (4417) + Chase Prime Visa (8802)" in dash
    assert "$3,500" in dash and "December 20" in dash
    assert "Loan to Alex Carver · due 12/20/26" in gauge
    assert "(LOAN.due||'2026-12-20')" in runway
    statements = json.loads((DATA / "cards" / "statements.json").read_text(encoding="utf-8"))
    assert {s["card_id"] for s in statements} == {"4417", "8802"}
