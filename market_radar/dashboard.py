from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from market_radar.digest import build_decision_digest
from market_radar.signals import build_decision_queue
from market_radar.storage import connect, init_db


CSS = """
body { font-family: Georgia, 'Times New Roman', serif; background: #f2eee6; color: #1b1a17; margin: 0; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 28px 24px 64px; }
.hero { background: linear-gradient(135deg, #1f3b4d, #81654b); color: #f8f4ee; border-radius: 22px; padding: 28px 30px; margin-bottom: 22px; }
.hero h1 { margin: 0 0 8px; font-size: 38px; }
.hero p { margin: 0; max-width: 820px; line-height: 1.5; }
.toolbar { display: flex; gap: 12px; flex-wrap: wrap; margin: 18px 0 22px; }
.chip { display: inline-block; border-radius: 999px; padding: 6px 11px; font-size: 12px; letter-spacing: .04em; text-transform: uppercase; }
.chip.web { background: #dde9ff; color: #19355a; }
.chip.github { background: #e8e1ff; color: #3d2969; }
.chip.readme { background: #fff1ce; color: #6a4f0b; }
.chip.release { background: #d6f3df; color: #19512e; }
.chip.adopt_now { background: #d8f3df; color: #14532d; }
.chip.backlog { background: #e6ecff; color: #274084; }
.chip.watch { background: #fff1ce; color: #7c5b0d; }
.chip.ignore { background: #f1e5e5; color: #6f2d2d; }
.chip.differentiate { background: #f3dff2; color: #6e2467; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 18px; }
.stat { background: #fffaf2; border-radius: 18px; padding: 16px 18px; box-shadow: 0 8px 22px rgba(28, 24, 20, 0.06); }
.stat .label { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: #78695c; }
.stat .value { font-size: 30px; font-weight: 700; margin-top: 8px; }
.grid { display: grid; gap: 16px; }
.digest-grid { display: grid; gap: 16px; margin-bottom: 24px; }
.card { background: #fffaf2; border-radius: 18px; padding: 18px 18px 16px; box-shadow: 0 8px 22px rgba(28, 24, 20, 0.06); }
.digest-card { background: linear-gradient(145deg, #fff9ef, #fff3db); border-radius: 18px; padding: 18px 18px 16px; box-shadow: 0 10px 26px rgba(48, 37, 22, 0.08); }
.meta { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.title { font-size: 22px; margin: 0 0 10px; }
.summary { line-height: 1.55; margin: 0 0 14px; }
.footer { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; font-size: 13px; color: #665a50; }
.score { font-weight: 700; color: #1f3b4d; }
a { color: #1e4e74; text-decoration: none; }
code { background: rgba(31, 59, 77, 0.08); padding: 2px 6px; border-radius: 6px; }
"""


def serve_dashboard(db_path: Path, host: str, port: int) -> None:
    init_db(db_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path not in {"/", "/index.html"}:
                self.send_error(404)
                return

            params = parse_qs(parsed.query)
            product = params.get("product", [None])[0]
            limit = int(params.get("limit", ["20"])[0])

            with connect(db_path) as connection:
                queue = build_decision_queue(connection, product_slug=product, limit=limit)
                digest = build_decision_digest(connection, product_slug=product, limit=5)

            html_text = render_dashboard(queue, digest=digest, product=product, limit=limit)
            body = html_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Market Radar dashboard running at http://{host}:{port}")
    server.serve_forever()


def render_dashboard(queue: list[dict], digest: list[dict], product: str | None, limit: int) -> str:
    stats = summarize(queue)
    digest_cards = "\n".join(render_digest_card(item) for item in digest) or "<p>Kein Digest vorhanden.</p>"
    cards = "\n".join(render_card(item) for item in queue) or "<p>Keine Signale vorhanden.</p>"
    product_label = html.escape(product) if product else "all products"
    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Market Radar</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>Market Radar</h1>
      <p>Decision Queue fuer <code>{product_label}</code>. Die Ansicht kombiniert Web- und GitHub-Signale
      und zeigt GitHub-Quellen explizit als <code>readme</code> oder <code>release</code>.</p>
    </section>
    <div class="toolbar">
      <span class="chip web">web</span>
      <span class="chip github">github</span>
      <span class="chip readme">readme</span>
      <span class="chip release">release</span>
      <span class="chip backlog">limit {limit}</span>
    </div>
    <section class="stats">
      <div class="stat"><div class="label">Signale</div><div class="value">{stats["total"]}</div></div>
      <div class="stat"><div class="label">Adopt Now</div><div class="value">{stats["adopt_now"]}</div></div>
      <div class="stat"><div class="label">GitHub</div><div class="value">{stats["github"]}</div></div>
      <div class="stat"><div class="label">Web</div><div class="value">{stats["web"]}</div></div>
    </section>
    <section class="digest-grid">
      {digest_cards}
    </section>
    <section class="grid">
      {cards}
    </section>
  </div>
</body>
</html>"""


def render_card(item: dict) -> str:
    source_url = item["source_url"]
    source_link = source_url_to_link(source_url)
    source_text = source_url
    return f"""
    <article class="card">
      <div class="meta">
        <span class="chip {html.escape(item['recommendation'])}">{html.escape(item['recommendation'])}</span>
        <span class="chip {html.escape(item['source_type'])}">{html.escape(item['source_type'])}</span>
        <span class="chip {html.escape(item['source_kind'])}">{html.escape(item['source_kind'])}</span>
        <span class="chip backlog">{html.escape(item['product_slug'])}</span>
        <span class="chip backlog">{html.escape(item['competitor_slug'])}</span>
      </div>
      <h2 class="title">{html.escape(item['title'])}</h2>
      <p class="summary">{html.escape(item['summary'])}</p>
      <div class="footer">
        <span><strong>Quelle:</strong> <a href="{html.escape(source_link)}">{html.escape(source_text)}</a></span>
        <span class="score">Score {item['priority_score']:.3f}</span>
        <span>{html.escape(item['detected_at'])}</span>
      </div>
    </article>
    """


def render_digest_card(item: dict) -> str:
    competitors = ", ".join(item["competitors"])
    sources = ", ".join(item["source_mix"])
    evidence = " | ".join(item["evidence"][:3])
    return f"""
    <article class="digest-card">
      <div class="meta">
        <span class="chip {html.escape(item['recommendation'])}">{html.escape(item['recommendation'])}</span>
        <span class="chip backlog">{html.escape(item['product_slug'])}</span>
        <span class="chip backlog">{html.escape(item['signal_label'])}</span>
      </div>
      <h2 class="title">{html.escape(item['signal_label'])}</h2>
      <p class="summary">{html.escape(item['decision'])}</p>
      <div class="footer">
        <span><strong>Kandidaten:</strong> {html.escape(competitors)}</span>
        <span><strong>Quellen:</strong> {html.escape(sources)}</span>
        <span class="score">Digest {item['priority_score']:.3f}</span>
      </div>
      <p class="summary"><strong>Evidenz:</strong> {html.escape(evidence)}</p>
    </article>
    """


def source_url_to_link(source_url: str) -> str:
    if not source_url.startswith("github://"):
        return source_url
    tail = source_url.removeprefix("github://")
    repo_name, _, kind = tail.rpartition("/")
    if kind == "readme":
        return f"https://github.com/{repo_name}"
    if kind == "release":
        return f"https://github.com/{repo_name}/releases/latest"
    return f"https://github.com/{repo_name}"


def summarize(queue: list[dict]) -> dict[str, int]:
    summary = {"total": len(queue), "adopt_now": 0, "github": 0, "web": 0}
    for item in queue:
        if item["recommendation"] == "adopt_now":
            summary["adopt_now"] += 1
        if item["source_type"] == "github":
            summary["github"] += 1
        else:
            summary["web"] += 1
    return summary
