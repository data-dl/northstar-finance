# -*- coding: utf-8 -*-
"""Build the static, shareable demo in docs/ (what GitHub Pages serves).

The demo is the rendered output of `python update.py` on the sample data, with the three
things a hosted page cannot do replaced by self-contained stand-ins:

* the Gmail-backed *Update spending* button plays back a scripted sync of invented alerts;
* the portfolio gauge's API-key price refresh becomes *Simulate a trading day*;
* "today" is frozen at the sample's as-of date, so freshness labels never rot;

plus a SAMPLE DATA banner on every page and a short "about this demo" panel. Every replacement
must match exactly once, so a template change fails this build instead of silently shipping a
half-converted page.

    python update.py && python tools/build_demo.py
"""
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT, DOCS = ROOT / "output", ROOT / "docs"
DEMO_TODAY_JS = "new Date('2026-09-12T12:00:00')"

BANNER_CSS = """
  .demo-intro{margin-bottom:16px}.demo-intro h2{font-size:22px;letter-spacing:-.025em;margin:6px 0 10px;text-wrap:balance}.demo-intro p{color:var(--muted);margin:0 0 10px;max-width:80ch;font-size:15px}.demo-intro ol{margin:0 0 12px;padding-left:22px;color:var(--muted);font-size:15px;max-width:80ch}.demo-intro li{margin:5px 0}.demo-intro b{color:var(--ink)}.demo-intro .feedback{border-top:1px solid var(--line);padding-top:12px;color:var(--ink);margin-bottom:0}
  .demo-banner{background:#ff8c1a;color:#1a1200;font:700 14px/1.45 ui-sans-serif,system-ui,"Segoe UI",sans-serif;padding:11px 18px;text-align:center;letter-spacing:.01em;position:relative;z-index:30}
  .demo-banner a{color:inherit}
  .demo-banner b{display:inline-block;background:#1a1200;color:#ffd9a8;padding:2px 8px;border-radius:6px;letter-spacing:.12em;font-size:11.5px;margin-right:9px;vertical-align:1px}
  .demo-chip{display:inline-block;margin-left:8px;background:#ff8c1a;color:#1a1200;font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;border-radius:999px;vertical-align:2px}
"""
BANNER_HTML = ('<div class="demo-banner" role="note"><b>SAMPLE DATA</b>Nothing on this page is real. Every balance, transaction, '
               'merchant, account and person was generated for a fictional household, as of Sep 12, 2026. '
               '<a href="https://github.com/data-dl/northstar-finance">Source and generator on GitHub</a>.</div>')


def apply(html, repl, label):
    for item in repl:
        old, new = item[0], item[1]
        count = item[2] if len(item) > 2 else 1
        n = html.count(old)
        if n != count:
            raise SystemExit(f"[{label}] expected {count} match(es), found {n}:\n   {old[:160]!r}")
        html = html.replace(old, new)
    return html


def rx(html, pattern, new, label, count=1):
    found = re.findall(pattern, html, flags=re.S)
    if len(found) != count:
        raise SystemExit(f"[{label}] regex expected {count}, found {len(found)}: {pattern[:120]!r}")
    return re.sub(pattern, lambda m: new, html, flags=re.S)


def add_banner(html):
    html = html.replace("</style>", BANNER_CSS + "</style>", 1)
    return re.sub(r"<body>", "<body>\n" + BANNER_HTML, html, count=1)


def main():
    if not (OUT / "data.js").exists():
        raise SystemExit("output/data.js is missing -- run `python update.py` first")
    DOCS.mkdir(exist_ok=True)
    version = re.search(r'data\.js\?v=([A-Za-z0-9]+)', (OUT / "index.html").read_text(encoding="utf-8")).group(1)
    src = f'<script src="data.js?v={version}"></script>'
    plain = '<script src="data.js"></script>'

    # ---- index
    idx = (OUT / "index.html").read_text(encoding="utf-8").replace(src, plain, 1)
    idx = apply(idx, [
        ('<meta name="description" content="Private, local financial command center for cash flow, resilience, and portfolio decisions.">',
         '<meta name="description" content="Demo of a personal financial command center, running entirely on generated sample data.">'),
        ("<title>Financial Command Center</title>", "<title>Northstar Demo</title>"),
        ("<b>Northstar 2.0</b><small>Private financial operating system</small>",
         "<b>Northstar 2.0</b><small>Demo · every number is generated</small>"),
        ("""        <p>This page was opened as a file, so the button can't reach Gmail. Run
           <b>python tools/serve.py</b> (or <b>tools/Northstar (live).cmd</b>) to get a working button, or
           <b>python tools/sync_alerts.py --rebuild</b> to update once.</p>""",
         """        <p><b>How the real one works.</b> The card issuer emails an alert for every transaction. The pipeline reads those
           alerts straight from Gmail (read-only scope), parses card, merchant and amount, cross-checks the subject
           against the body, de-duplicates against the statements already on file, and parks anything ambiguous
           (declines, fuel holds, unknown cards) in a review lane instead of guessing.</p>
        <p><b>In this demo</b> the button plays back a scripted sync with invented alerts, so you can see the tally move.</p>"""),
        ('<main>\n  <section class="cockpit">',
         """<main>
  <section class="panel demo-intro" aria-label="About this demo">
    <div class="eyebrow">About this demo</div>
    <h2>A personal-finance command center, running on generated money</h2>
    <p>Northstar is four linked dashboards on top of a Python pipeline that reads bank statements, card exports,
       paystubs and Amazon, Chewy and Venmo history, reconciles them against each other (20 integrity checks), and
       rebuilds these pages. What you are looking at is the same tool pointed at a synthetic household produced by
       the repository's generator, so nothing here is private and nothing is real.</p>
    <ol>
      <li><b>Update spending</b>, just below: the real version reads the card issuer's transaction-alert emails straight from
          Gmail and keeps a running tally of what has been spent since the last statement. Here it plays back a scripted sync.</li>
      <li><b>Money dashboard</b> in the top nav: sixteen tabs over two years of statements. <i>This Month</i>, <i>Corner Stores</i>
          and <i>Points</i> are good places to start.</li>
      <li><b>Portfolio gauge</b>, then <b>Simulate a trading day</b>: every account reconciled to one balance sheet, with dials for
          the day's move. The real one pulls live quotes.</li>
    </ol>
    <p class="feedback">The code, the data generator and the design notes are at
       <a href="https://github.com/data-dl/northstar-finance">github.com/data-dl/northstar-finance</a>.</p>
  </section>
  <section class="cockpit">"""),
        ('<p class="foot">Private local dashboard. Estimates',
         '<p class="foot">Demo of a private local dashboard, running on generated sample data. Estimates'),
        ("var then=Date.UTC(+q[0],+q[1]-1,+q[2]), now=new Date();", "var then=Date.UTC(+q[0],+q[1]-1,+q[2]), now=DEMO_TODAY;"),
        ("var D=window.DASHBOARD_DATA||{}, S=D.summary||{},", "var DEMO_TODAY=" + DEMO_TODAY_JS + ";\n  var D=window.DASHBOARD_DATA||{}, S=D.summary||{},"),
        ("var todayKey=new Date().toISOString().slice(0,10);", "var todayKey=DEMO_TODAY.toISOString().slice(0,10);"),
        ("? ('Alerts last pulled from Gmail on '+A.ingested_at+'.')",
         "? ('Alerts last pulled from Gmail on '+A.ingested_at+' (in the demo, a scripted sample rather than a live mailbox).')"),
    ], "index")
    idx = rx(idx, r"  // ---- live sync, available only when served by tools/serve\.py -----------.*?\n  \}\)\(\);\n",
             r"""  // ---- demo sync: a scripted stand-in for the Gmail fetch -------------------
  // The real page asks a local server to read Gmail and rebuild. A hosted demo
  // has neither, so the button plays back invented alerts and re-renders the tally.
  (function(){
    var btn=$('tallySync'), msg=$('tallyLiveMsg');
    msg.textContent='Demo: plays back a scripted sync with invented alerts.';
    var POOL=[['FOURTH STREET MARKET',5.35,'4417'],['LAKEVIEW TRANSIT AUTH',2.75,'4417'],['AMAZON.COM*7R2WQ1M',18.49,'8802'],
              ['STARBUCKS #22910',6.85,'4417'],['KROGER #445',31.06,'4417'],['CHEWY.COM',26.49,'4417'],['LYFT *RIDE MON 6PM',11.30,'4417'],
              ['CORNER BOOKS LAKEVIEW',17.50,'4417'],['SUNFIRE TAQUERIA',14.20,'4417'],['TRADER JOE\'S #712',27.83,'4417']];
    var TIMES=['08:12','12:41','18:07','20:26'];
    var round=0;
    btn.addEventListener('click',function(){
      btn.disabled=true; btn.textContent='Checking…';
      msg.textContent='Reading Gmail and rebuilding… (simulated)';
      setTimeout(function(){
        var A=D.card_alerts;
        if(!A||!A.rows){ btn.disabled=false; btn.textContent='↻ Update spending'; return; }
        var n=2+(round%2), day=12+Math.floor(round/2), date='2026-09-'+String(day).padStart(2,'0');
        for(var i=0;i<n;i++){
          var p=POOL[(round*3+i)%POOL.length];
          A.rows.unshift({alert_id:'demo'+round+'_'+i, datetime:date+' '+TIMES[(round+i)%TIMES.length], date:date, card_id:p[2],
            card_name:(p[2]==='4417'?'Chase Freedom':'Chase Prime Visa'), merchant:p[0], amount:p[1], kind:'purchase'});
        }
        (A.by_card||[]).forEach(function(c){
          var rs=A.rows.filter(function(r){return r.card_id===c.card_id});
          c.count=rs.length; c.net=+rs.reduce(function(a,r){return a+r.amount},0).toFixed(2);
        });
        (A.cards||[]).forEach(function(c){
          if(!c.alerts_enabled) return;
          var rs=A.rows.filter(function(r){return r.card_id===c.card_id});
          c.count=rs.length; c.net=+rs.reduce(function(a,r){return a+r.amount},0).toFixed(2);
        });
        A.count=A.rows.length; A.newest=date; A.ingested_at=date+' '+TIMES[(round+1)%TIMES.length];
        round++;
        renderTally();
        msg.textContent=n+' new, '+A.rows.length+' on file, '+((A.review||[]).length)+' needing review. Rebuilt. (Simulated: these alerts are invented.)';
        btn.disabled=false; btn.textContent='↻ Update spending';
      },1400);
    });
  })();
""", "index live-sync block")
    idx = add_banner(idx)

    # ---- dashboard
    dash = (OUT / "dashboard.html").read_text(encoding="utf-8").replace(src, plain, 1)
    dash = apply(dash, [
        ("<title>Money Dashboard</title>", "<title>Money Dashboard — Sample Data</title>"),
        ('<a class="suite-brand" href="index.html"><i></i>Northstar 2.0</a>',
         '<a class="suite-brand" href="index.html"><i></i>Northstar 2.0 <span class="demo-chip">sample data</span></a>'),
        ('<div class="eyebrow">Personal finance · all accounts reconciled</div>',
         '<div class="eyebrow">Demo · sample data · all accounts reconciled</div>'),
        ("var D = window.DASHBOARD_DATA || {};", "var D = window.DASHBOARD_DATA || {};\n  var DEMO_TODAY = " + DEMO_TODAY_JS + ";"),
        ("var then=Date.UTC(+p[0],+p[1]-1,+p[2]), now=new Date();", "var then=Date.UTC(+p[0],+p[1]-1,+p[2]), now=DEMO_TODAY;"),
        ("var p=normalized.split('-').map(Number), now=new Date();", "var p=normalized.split('-').map(Number), now=DEMO_TODAY;"),
    ], "dashboard")
    dash = add_banner(dash)

    # ---- gauge
    g = (OUT / "portfolio_gauge.html").read_text(encoding="utf-8").replace(src, plain, 1)
    g = apply(g, [
        ("<title>Portfolio Live Gauge</title>", "<title>Portfolio Gauge — Sample Data</title>"),
        ('<a class="suite-brand" href="index.html"><i></i>Northstar 2.0</a>',
         '<a class="suite-brand" href="index.html"><i></i>Northstar 2.0 <span class="demo-chip">sample data</span></a>'),
        ("""  <div class="controls">
    <select id="provider" title="Price data provider">
      <option value="finnhub">Finnhub</option>
      <option value="alphavantage">Alpha Vantage</option>
    </select>
    <input type="password" id="apiKey" placeholder="API key (stored only in this browser)" autocomplete="off">
    <button class="primary" id="refreshBtn">🔄 Refresh live prices</button>
    <label class="toggle"><input type="checkbox" id="autoChk"> auto every 5 min</label>
  </div>""",
         """  <div class="controls">
    <button class="primary" id="simBtn">🎲 Simulate a trading day</button>
    <button id="resetBtn">Reset to baseline</button>
    <span class="hint" style="flex:1 1 260px">Demo stand-in for the live-quote refresh. The real page pulls prices from Finnhub or Alpha Vantage with your own API key; this one moves every ticker by a random daily amount so the dials swing.</span>
  </div>"""),
        ("const LS = window.localStorage;", "const LS = (function(){ var m={}; return {getItem:function(k){return (k in m)?m[k]:null}, setItem:function(k,v){m[k]=String(v)}, removeItem:function(k){delete m[k]}}; })();  // demo: nothing persists between loads"),
        ('const moveContext=lastUpdated?"today · whole portfolio":"baseline · refresh prices for today\'s move";', 'const moveContext=lastUpdated?"simulated day · whole portfolio":"baseline · simulate a day to see a move";'),
        ("`<b style=\"color:${bCol}\">${BENCH.name} ${lastUpdated?'today':'baseline'} ${bs}${Math.abs(bPct).toFixed(2)}%</b>`", "`<b style=\"color:${bCol}\">${BENCH.name} ${lastUpdated?'simulated day':'baseline'} ${bs}${Math.abs(bPct).toFixed(2)}%</b>`"),
        ('? "Prices refreshed: "+new Date(lastUpdated).toLocaleString("en-US",{dateStyle:"medium",timeStyle:"short"})+(priceAgeHours>18?" · saved prices may be stale":"")',
         '? "Simulated prices, generated "+new Date(lastUpdated).toLocaleString("en-US",{dateStyle:"medium",timeStyle:"short"})'),
        ('`Cash, bank and retirement balances are editable inline (saved in this browser only). `+',
         '`Cash, bank and retirement balances are editable inline (in the demo, edits last until you reload). `+'),
        ("`Live prices via <b>Finnhub</b> <code>/quote</code> (60 calls/min free — refresh freely) or <b>Alpha Vantage</b> <code>GLOBAL_QUOTE</code> (25/day free); pick a provider above and paste that provider's key. Finnhub doesn't quote the VFIFX mutual fund, so its NAV is pulled from Alpha Vantage when a key is saved, otherwise kept. Free data may be ~15 min delayed. `+",
         "`In the real tool, live prices come from <b>Finnhub</b> or <b>Alpha Vantage</b> with your own API key (Finnhub doesn't quote the VFIFX mutual fund, so its NAV comes from Alpha Vantage). This demo simulates a trading day instead. `+"),
        ("`Balances come from data/balances/, never from a credit-monitoring app. Not investment advice.`;",
         "`Not investment advice — and none of these holdings are real.`;"),
    ], "gauge")
    g = rx(g, r"// ============ Price providers ============.*?(?=function loadPrices\(\)\{)", "", "gauge providers block")
    g = rx(g, r"// ============ Live refresh \(provider-agnostic\) ============.*?</script>",
           r"""// ============ Demo: simulated trading day ============
// The real page pulls live quotes from Finnhub / Alpha Vantage with the viewer's own
// key. A hosted demo cannot reach those APIs, so this stands in: every ticker gets
// a plausible random daily move (a shared market factor plus its own noise).
let simSeed = 344;
function rnd(){ simSeed = (simSeed * 1103515245 + 12345) % 2147483648; return simSeed / 2147483648; }
function gauss(){ return (rnd()+rnd()+rnd()+rnd()-2)*1.7; }
const HIGH_VOL = new Set(["NVDA","SOFI","ENPH","RIVN"]);
function simulate(){
  const next={...prices};
  const market = gauss()*0.8;                                   // the day's market move, in %
  for(const sym of fetchList){
    const base=q(sym);
    const vol = sym===BENCH.sym ? 0.35 : (sym===FUND.sym ? 0.6 : (HIGH_VOL.has(sym) ? 3.0 : 1.5));
    const beta = sym===FUND.sym ? 0.85 : (sym===BENCH.sym ? 1 : 1.1);
    const move = market*beta + gauss()*vol;
    next[sym] = {p:+(base.p*(1+move/100)).toFixed(2), pc:base.p};   // yesterday's close = where we were
  }
  prices=next; lastUpdated=new Date().toISOString();
  render();
  setMsg("Simulated one trading day: every price moved by a random amount. None of these are real quotes.","ok");
}
function resetSim(){ prices=JSON.parse(JSON.stringify(BASE)); overrides={}; lastUpdated=null; render(); setMsg("Back to the imported baseline.",""); }
function setMsg(t,cls){ const m=px("msg"); m.textContent=t; m.className="msg "+(cls||""); }
function updateHint(){ px("hint").textContent=""; }

px("simBtn").addEventListener("click",simulate);
px("resetBtn").addEventListener("click",resetSim);

// Dials are built once, then only their needles move on each render.
px("gaugeSvgPicks").innerHTML = gaugeSvg("picks", PICKS_RANGE);
px("gaugeSvgAll").innerHTML   = gaugeSvg("all",   ALL_RANGE);

render();
setInterval(updateMarket,60000);
</script>""", "gauge refresh block")
    g = add_banner(g)

    # ---- runway
    rw = (OUT / "runway.html").read_text(encoding="utf-8").replace(src, plain, 1)
    rw = apply(rw, [
        ("<title>Emergency Runway Calculator</title>", "<title>Emergency Runway — Sample Data</title>"),
        ('<a class="suite-brand" href="index.html"><i></i>Northstar 2.0</a>',
         '<a class="suite-brand" href="index.html"><i></i>Northstar 2.0 <span class="demo-chip">sample data</span></a>'),
    ], "runway")
    rw = add_banner(rw)

    for name, html in (("index.html", idx), ("dashboard.html", dash), ("portfolio_gauge.html", g), ("runway.html", rw)):
        (DOCS / name).write_text(html, encoding="utf-8")
        print(f"wrote docs/{name} ({len(html):,} chars)")
    shutil.copyfile(OUT / "data.js", DOCS / "data.js")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    print("wrote docs/data.js")


if __name__ == "__main__":
    main()
