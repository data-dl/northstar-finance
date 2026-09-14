"""Writes output/data.js from the metrics dict and copies the static, data-driven HTML templates. See SPEC.md Sec.8."""
import json
from pathlib import Path


def render(metrics: dict, templates_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    data_js = "window.DASHBOARD_DATA = " + json.dumps(metrics, indent=2, default=str) + ";\n"
    (output_dir / "data.js").write_text(data_js, encoding="utf-8")

    # A user often keeps these local dashboards open between refreshes.  Give each
    # generated page a new data.js URL so a normal browser reload cannot reuse a
    # stale cached dataset after update.py has successfully rebuilt the metrics.
    data_version = "".join(ch for ch in str(metrics.get("generated_at", "current")) if ch.isalnum())
    data_script = '<script src="data.js"></script>'
    for name in ("index.html", "dashboard.html", "runway.html"):
        template = (templates_dir / name).read_text(encoding="utf-8")
        if data_script not in template:
            raise ValueError(f"{templates_dir / name} is missing {data_script}")
        rendered = template.replace(
            data_script,
            f'<script src="data.js?v={data_version}"></script>',
            1,
        )
        (output_dir / name).write_text(rendered, encoding="utf-8")

    gauge_template = templates_dir / "portfolio_gauge.html"
    if gauge_template.exists():
        gauge_html = gauge_template.read_text(encoding="utf-8")
        if data_script not in gauge_html:
            raise ValueError(f"{gauge_template} is missing {data_script}")
        gauge_html = gauge_html.replace(
            data_script,
            f'<script src="data.js?v={data_version}"></script>',
            1,
        )
        (output_dir / "portfolio_gauge.html").write_text(gauge_html, encoding="utf-8")
