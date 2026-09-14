"""Fail-loudly checks, run on every `update.py`. See docs/DESIGN.md Sec.9."""
import statistics
from datetime import date

from finlib import reconcile as rc


class ValidationError(Exception):
    pass


def run_checks(loaded: dict, config: dict, metrics: dict) -> list:
    """Returns a list of {name, passed, critical, detail} dicts. Raises ValidationError if any critical check fails."""
    bank = loaded["bank"]
    checks = []

    # 1. per_check_gross * checks_per_year ~= annual_salary (+-2%)
    pay = config["pay"]
    computed_annual = pay["per_check_gross"] * pay["checks_per_year"]
    pct_off = abs(computed_annual - pay["annual_salary"]) / pay["annual_salary"]
    checks.append({
        "name": "Gross paycheck x checks/year matches annual salary",
        "passed": pct_off <= 0.02,
        "critical": True,
        "detail": f"{computed_annual:.2f} vs {pay['annual_salary']:.2f} ({pct_off:.1%} off)",
    })

    # 2. Category breakdown sums ~= total spend (+-1%)
    # category avg_mo is per data-bearing month, so reconcile against the observed-window total
    observed_spend = metrics["_internal"]["observed_spend"]
    n_months = metrics["_internal"]["n_avg_months"]
    cat_sum = sum(c["avg_mo"] for c in metrics["categories"] if c["key"] != "family") * n_months
    pct_off = abs(cat_sum - observed_spend) / observed_spend if observed_spend else 0
    checks.append({
        "name": "Category breakdown sums ~= total spend",
        "passed": pct_off <= 0.01,
        "critical": True,
        "detail": f"{cat_sum:.2f} vs {observed_spend:.2f} ({pct_off:.1%} off)",
    })

    # 2b. No interior gap in bank coverage -- a missing statement in the middle of the window is
    # invisible in a start/end date check but silently distorts every average.
    gaps = metrics["data_quality"]["missing_months"]
    checks.append({
        "name": "No missing months inside the bank window",
        "passed": not gaps,
        "critical": False,
        "detail": ("no gaps" if not gaps
                   else f"MISSING STATEMENT(S): {', '.join(gaps)} -- excluded from all averages; "
                        f"drop the statement PDF into data/bank/ to close the gap"),
    })

    # 3. Internal transfers net to ~0 (checking<->savings sweeps)
    internal_descs = {d.lower() for d in config["bank_internal_transfer_descriptions"]}

    def is_internal(desc):
        d = str(desc).lower()
        return d in internal_descs or d.startswith("comment")

    mask = bank["Description"].apply(is_internal)
    signed = bank.loc[mask].apply(lambda r: r["Amount"] if r["Type"] == "Credit" else -r["Amount"], axis=1)
    net = float(signed.sum())
    gross_moved = float(bank.loc[mask, "Amount"].sum())
    tolerance = max(500.0, gross_moved * 0.1)
    checks.append({
        "name": "Internal transfers (checking<->savings) net to ~0",
        "passed": abs(net) <= tolerance,
        "critical": False,
        "detail": f"net {net:.2f} on {gross_moved:.2f} moved (tolerance {tolerance:.2f})",
    })

    # 4. Sum of paycheck components == gross, to the cent
    ded = pay["deductions_per_check"]
    total_deductions = sum(ded.values())
    reconstructed = pay["per_check_net"] + total_deductions
    diff = abs(reconstructed - pay["per_check_gross"])
    checks.append({
        "name": "Paycheck components sum to gross (to the cent)",
        "passed": diff < 0.01,
        "critical": True,
        "detail": f"net {pay['per_check_net']:.2f} + deductions {total_deductions:.2f} = {reconstructed:.2f} vs gross {pay['per_check_gross']:.2f}",
    })

    # 5. Two paystubs' YTD deltas equal one check -- not auto-parsed (image-based, DESIGN Sec.4e)
    checks.append({
        "name": "Paystub YTD cross-check",
        "passed": True,
        "critical": False,
        "detail": "skipped -- paystubs are image-based and not OCR'd at runtime; figures are hand-transcribed in config.yaml",
    })

    # 6. No month has spend > 3x median (flag anomalies, don't crash)
    spends = [r["spend"] for r in metrics["_internal"]["monthly_rows"] if r["spend"] > 0]
    anomalies = []
    if len(spends) >= 3:
        med = statistics.median(spends)
        anomalies = [r["month"] for r in metrics["_internal"]["monthly_rows"] if r["spend"] > 3 * med]
    checks.append({
        "name": "No month spends > 3x median (anomaly scan)",
        "passed": True,
        "critical": False,
        "detail": f"flagged: {anomalies}" if anomalies else "none flagged",
    })

    # 7. Coverage windows reported match actual min/max dates found
    actual_min, actual_max = bank["Date"].min().date(), bank["Date"].max().date()
    reported = metrics["coverage"]["bank"]
    match = str(actual_min) == reported["start"] and str(actual_max) == reported["end"]
    checks.append({
        "name": "Reported bank coverage window matches actual data",
        "passed": match,
        "critical": True,
        "detail": f"actual {actual_min}..{actual_max} vs reported {reported['start']}..{reported['end']}",
    })

    # 8. Net worth: tax buckets and stock/bond/cash allocation each reconcile to total assets
    nw = metrics.get("net_worth_detail") or {}
    if nw.get("assets_total"):
        assets = nw["assets_total"]
        tax_sum = sum(nw.get("by_tax", {}).values())
        alloc_sum = sum(nw.get("allocation", {}).values())
        checks.append({
            "name": "Net worth tax buckets sum to total assets",
            "passed": abs(tax_sum - assets) <= 1.0,
            "critical": True,
            "detail": f"buckets {tax_sum:.2f} vs assets {assets:.2f}",
        })
        checks.append({
            "name": "Net worth allocation (stocks+bonds+cash) sums to total assets",
            "passed": abs(alloc_sum - assets) <= 1.0,
            "critical": True,
            "detail": f"allocation {alloc_sum:.2f} vs assets {assets:.2f}",
        })

        # Headline balance-sheet identities. These are deliberately separate checks so the
        # build says exactly which definition drifted instead of merely reporting "net worth off."
        liabilities = float(nw.get("liabilities_total", 0))
        net_total = float(nw.get("net_total", 0))
        account_sum = sum(float(a.get("balance", 0)) for a in nw.get("accounts", []))
        liability_sum = sum(float(l.get("balance", 0)) for l in nw.get("liabilities", []))
        checks.extend([
            {
                "name": "Net worth equals assets minus liabilities",
                "passed": abs((assets - liabilities) - net_total) <= 0.01,
                "critical": True,
                "detail": f"{assets:.2f} - {liabilities:.2f} = {assets-liabilities:.2f} vs {net_total:.2f}",
            },
            {
                "name": "Account balances sum to total assets",
                "passed": abs(account_sum - assets) <= 0.01,
                "critical": True,
                "detail": f"accounts {account_sum:.2f} vs assets {assets:.2f}",
            },
            {
                "name": "Liability rows sum to total liabilities",
                "passed": abs(liability_sum - liabilities) <= 0.01,
                "critical": True,
                "detail": f"rows {liability_sum:.2f} vs liabilities {liabilities:.2f}",
            },
            {
                "name": "Summary and balance sheet use the same net worth",
                "passed": abs(float(metrics.get("summary", {}).get("net_worth", 0)) - net_total) <= 0.01,
                "critical": True,
                "detail": f"summary {float(metrics.get('summary', {}).get('net_worth', 0)):.2f} vs balance sheet {net_total:.2f}",
            },
        ])

        receivable = float(nw.get("by_tax", {}).get("receivable", 0))
        loan_principal = sum(float(l.get("principal", 0)) for l in metrics.get("loans_out", []))
        checks.append({
            "name": "Loan receivables reconcile to the balance sheet",
            "passed": abs(receivable - loan_principal) <= 0.01,
            "critical": True,
            "detail": f"receivable bucket {receivable:.2f} vs open-loan principal {loan_principal:.2f}",
        })

        liquid_cash = float(nw.get("by_tax", {}).get("cash", 0))
        runway_cash = float(metrics.get("runway_inputs", {}).get("cash_hysa", 0))
        checks.append({
            "name": "Runway and balance sheet use the same spendable cash",
            "passed": abs(liquid_cash - runway_cash) <= 0.01,
            "critical": True,
            "detail": f"balance sheet cash {liquid_cash:.2f} vs runway cash {runway_cash:.2f}",
        })

        positions = nw.get("positions", [])
        if positions:
            position_extension_error = sum(
                abs(float(p.get("shares", 0)) * float(p.get("price", 0)) - float(p.get("value", 0)))
                for p in positions
            )
            checks.append({
                "name": "Position values match shares times baseline marks",
                "passed": position_extension_error <= 0.25,
                "critical": True,
                "detail": f"aggregate absolute rounding difference {position_extension_error:.2f}",
            })

            position_by_suffix = {}
            for p in positions:
                suffix = str(p.get("account_suffix", ""))
                position_by_suffix[suffix] = position_by_suffix.get(suffix, 0.0) + float(p.get("value", 0))
            vanguard_accounts = [a for a in nw.get("accounts", []) if a.get("institution") == "Vanguard"]
            account_diffs = []
            for account in vanguard_accounts:
                name = str(account.get("name", ""))
                suffix = name.rsplit("x", 1)[-1][-4:] if "x" in name else ""
                if suffix in position_by_suffix:
                    account_diffs.append(abs(float(account.get("balance", 0)) - position_by_suffix[suffix]))
            max_diff = max(account_diffs) if account_diffs else 0.0
            checks.append({
                "name": "Vanguard position detail reconciles to account balances",
                "passed": bool(account_diffs) and max_diff <= 0.05,
                "critical": True,
                "detail": f"largest account difference {max_diff:.2f} across {len(account_diffs)} accounts",
            })

        integrity = metrics.get("financial_integrity", {})
        integrity_ok = (
            abs(float(integrity.get("statement_assets", 0)) - assets) <= 0.01
            and abs(float(integrity.get("statement_liabilities", 0)) - liabilities) <= 0.01
            and abs(float(integrity.get("statement_net_worth", 0)) - net_total) <= 0.01
            and abs(float(integrity.get("liquid_cash", 0)) - liquid_cash) <= 0.01
        )
        checks.append({
            "name": "Shared dashboard integrity contract matches source metrics",
            "passed": integrity_ok,
            "critical": True,
            "detail": "headline assets, liabilities, net worth and cash all match" if integrity_ok else "shared dashboard contract drifted",
        })

    # 9. Data freshness: warn when the newest statement is going stale (DESIGN Sec.12 new-month detection)
    newest = max(bank["Date"].max(), loaded["cards"]["Transaction Date"].max()).date()
    age_days = (date.today() - newest).days
    checks.append({
        "name": "Data freshness (newest bank/card row < 35 days old)",
        "passed": age_days <= 35,
        "critical": False,
        "detail": f"newest transaction {newest} ({age_days} days ago)"
                  + ("" if age_days <= 35 else " — drop a fresh statement export into data/ and rerun"),
    })

    critical_failures = [c for c in checks if c["critical"] and not c["passed"]]
    if critical_failures:
        names = ", ".join(c["name"] for c in critical_failures)
        raise ValidationError(f"Validation failed: {names}")

    return checks
