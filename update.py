#!/usr/bin/env python
"""Entry point: load -> reconcile -> compute -> validate -> render. See docs/DESIGN.md."""
import argparse
import sys
import time
import webbrowser
from pathlib import Path

import yaml

from finlib import loaders, metrics as metrics_lib, validate

ROOT = Path(__file__).resolve().parent

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


LOADER_FNS = {
    "bank": lambda data_dir, config: loaders.load_bank(data_dir, config),
    "cards": lambda data_dir, config: loaders.load_cards(data_dir, config["cards"]),
    "amazon": lambda data_dir, config: loaders.load_amazon(data_dir),
    "venmo": lambda data_dir, config: loaders.load_venmo(data_dir, config["identity"]["venmo_name"]),
}

# Optional sources: pipeline still runs if their data/ folder is absent.
OPTIONAL_LOADER_FNS = {
    "balances": lambda data_dir, config: loaders.load_balances(data_dir),
    "holdings": lambda data_dir, config: loaders.load_vanguard_holdings(data_dir),
    "chewy": lambda data_dir, config: loaders.load_chewy(data_dir),
    "card_statements": lambda data_dir, config: loaders.load_card_statements(data_dir, config["cards"]),
    "card_alerts": lambda data_dir, config: loaders.load_card_alerts(data_dir),
    "alert_review": lambda data_dir, config: loaders.load_alert_review(data_dir),
    "statement_balances": lambda data_dir, config: loaders.load_statement_balances(data_dir),
}


def load_all(config: dict, data_dir: Path) -> dict:
    loaded = {name: fn(data_dir, config) for name, fn in LOADER_FNS.items()}
    for name, fn in OPTIONAL_LOADER_FNS.items():
        loaded[name] = fn(data_dir, config)
    return loaded


def main():
    parser = argparse.ArgumentParser(description="Rebuild the personal finance dashboards.")
    parser.add_argument("--validate-only", action="store_true", help="Run validation checks and exit, no render.")
    parser.add_argument("--source", choices=["bank", "cards", "amazon", "venmo"], help="Only run one loader and print its shape, for debugging. Skips reconcile/validate/render.")
    parser.add_argument("--open", action="store_true", help="Open the dashboards in a browser after building.")
    parser.add_argument("--config", default=None, help="Path to config.yaml (default: config.yaml beside this script).")
    parser.add_argument("--data", default=None, help="Path to the data folder (default: data/ beside this script).")
    parser.add_argument("--output", default=None, help="Where to write the dashboards (default: output/ beside this script).")
    args = parser.parse_args()

    t0 = time.time()

    config_path = Path(args.config) if args.config else ROOT / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data_root = Path(args.data) if args.data else ROOT / "data"

    if args.source:
        df = LOADER_FNS[args.source](data_root, config)
        print(f"{args.source}: {len(df)} rows, columns: {list(df.columns)}")
        print(f"Done in {time.time()-t0:.1f}s (source-only)")
        return

    loaded = load_all(config, data_root)
    required = {name: loaded[name] for name in LOADER_FNS}
    if any(df is None or df.empty for df in required.values()):
        missing = [name for name, df in required.items() if df is None or df.empty]
        print(f"✗ No data loaded for: {', '.join(missing)}. Check data/ subfolders.", file=sys.stderr)
        sys.exit(1)

    bal = loaded.get("balances")
    bal_note = f"balances ({len(bal)} accounts)" if bal is not None and not bal.empty else "balances (none)"
    card_bills = loaded.get("card_statements")
    card_bill_note = f"card bills ({len(card_bills)} cards)" if card_bills is not None and not card_bills.empty else "card bills (none)"
    n_bank_pdf = len([p for p in (data_root / "bank").glob("*") if p.suffix.lower() == ".pdf"])
    print(
        f"✓ Loaded bank ({len(sorted((data_root / 'bank').glob('*.csv')))} csv + {n_bank_pdf} pdf), "
        f"cards ({len(sorted((data_root / 'cards').glob('*.csv')))}), "
        f"amazon ({len(sorted((data_root / 'amazon').glob('*.csv')))}), "
        f"venmo ({len(sorted((data_root / 'venmo').glob('*.csv')))}), paystubs (config), {bal_note}, {card_bill_note}"
    )

    metrics = metrics_lib.compute_metrics(loaded, config)

    s = metrics["summary"]
    n_months = metrics["coverage"]["bank"]["months"]
    print(
        f"✓ Reconciled: {n_months}-mo savings rate {s['savings_rate_takehome']:.0f}% "
        f"· avg spend ${s['avg_spend_mo']:,.0f}/mo · income verified"
    )

    try:
        checks = validate.run_checks(loaded, config, metrics)
    except validate.ValidationError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)

    n_pass = sum(1 for c in checks if c["passed"])
    metrics["validation"] = {
        "passed": n_pass,
        "total": len(checks),
        "all_passed": n_pass == len(checks),
        "checks": checks,
    }
    metrics.setdefault("_internal", {})["validation_count"] = f"{n_pass}/{len(checks)}"
    print(f"✓ Validation passed ({n_pass}/{len(checks)} checks)")
    for c in checks:
        mark = "✓" if c["passed"] else "✗"
        print(f"    {mark} {c['name']}: {c['detail']}")

    if args.validate_only:
        print(f"Done in {time.time()-t0:.1f}s (validate-only)")
        return

    from finlib import render as render_lib

    output_dir = Path(args.output) if args.output else ROOT / "output"
    render_lib.render(metrics, ROOT / "templates", output_dir)
    print(f"✓ Wrote {output_dir/'data.js'}")
    print(
        f"✓ Rendered {output_dir/'index.html'}, {output_dir/'dashboard.html'}, "
        f"{output_dir/'runway.html'}, {output_dir/'portfolio_gauge.html'}"
    )

    print(f"Done in {time.time()-t0:.1f}s")

    if args.open:
        webbrowser.open((output_dir / "dashboard.html").as_uri())
        webbrowser.open((output_dir / "runway.html").as_uri())


if __name__ == "__main__":
    main()
