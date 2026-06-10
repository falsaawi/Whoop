"""Routes for the human "buddy" body map.

- ``GET /api/body?days=N`` — organ-level health profile JSON (see
  :mod:`app.body`): each organ with a status, the metrics behind it, and the
  ICD-10 codes it links to (with the ones currently flagged).
- ``GET /body``            — a self-contained interactive page rendering a
  clickable anatomical figure, colour-coded by organ health.
"""
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.body import compute_body_profile
from app.database import get_db

router = APIRouter(tags=["body"])

_DATA_CACHE = "public, s-maxage=600, stale-while-revalidate=86400"
_PAGE_CACHE = "public, s-maxage=86400, stale-while-revalidate=604800"


@router.get("/api/body")
def api_body(
    response: Response,
    days: int = Query(90, ge=7, le=3650),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = _DATA_CACHE
    return compute_body_profile(db, days=days)


@router.get("/body", response_class=HTMLResponse)
def body_page() -> HTMLResponse:
    return HTMLResponse(_PAGE, headers={"Cache-Control": _PAGE_CACHE})


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Whoop Body Map</title>
  <style>
    :root {
      --bg: #0b0d12; --panel: #141821; --panel-2: #1b2030; --border: #232a3a;
      --text: #e7ebf3; --muted: #8a93a6; --accent: #4cd3a5;
      --ok: #16c47f; --watch: #f4c542; --alert: #ef4f4f; --unmon: #5b6478;
      --blue: #5aa7ff;
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0; padding: 0; background: var(--bg); color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif; -webkit-font-smoothing: antialiased;
    }
    a { color: var(--accent); text-decoration: none; }
    header {
      padding: 28px 32px 16px; display: flex; flex-wrap: wrap;
      align-items: flex-end; gap: 16px; justify-content: space-between;
      border-bottom: 1px solid var(--border);
    }
    header h1 { margin: 0; font-size: 26px; letter-spacing: -0.02em; }
    header .meta { color: var(--muted); font-size: 14px; margin-top: 6px; }
    .range {
      display: inline-flex; gap: 4px; background: var(--panel);
      border: 1px solid var(--border); padding: 4px; border-radius: 10px;
    }
    .range button {
      background: transparent; color: var(--muted); border: none;
      padding: 8px 14px; font-size: 13px; font-weight: 600; border-radius: 7px;
      cursor: pointer; transition: background 120ms, color 120ms;
    }
    .range button:hover { color: var(--text); }
    .range button.active { background: var(--panel-2); color: var(--text); }
    main { padding: 24px 32px 48px; max-width: 1200px; margin: 0 auto; }

    .status-banner {
      border-radius: 14px; padding: 18px 22px; border: 1px solid var(--border);
      background: var(--panel); margin-bottom: 20px; display: flex;
      align-items: center; gap: 18px; flex-wrap: wrap;
    }
    .status-banner.alert { border-color: rgba(239,79,79,.5); background: linear-gradient(160deg, rgba(239,79,79,.14), var(--panel) 60%); }
    .status-banner.watch { border-color: rgba(244,197,66,.5); background: linear-gradient(160deg, rgba(244,197,66,.12), var(--panel) 60%); }
    .status-banner.ok { border-color: rgba(22,196,127,.5); background: linear-gradient(160deg, rgba(22,196,127,.14), var(--panel) 60%); }
    .status-banner h2 { margin: 0; font-size: 20px; }
    .status-banner .pills { display: flex; gap: 8px; margin-left: auto; flex-wrap: wrap; }
    .pill { font-size: 12px; font-weight: 700; padding: 6px 11px; border-radius: 999px; border: 1px solid var(--border); }
    .pill.alert { color: var(--alert); } .pill.watch { color: var(--watch); }
    .pill.ok { color: var(--ok); } .pill.unmon { color: var(--unmon); }

    .layout { display: grid; grid-template-columns: 360px 1fr; gap: 20px; align-items: start; }
    .figure-card {
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 16px; padding: 18px; position: sticky; top: 16px;
    }
    .legend { display: flex; gap: 14px; justify-content: center; margin-top: 8px; flex-wrap: wrap; font-size: 12px; color: var(--muted); }
    .legend span { display: inline-flex; align-items: center; gap: 6px; }
    .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .dot.ok { background: var(--ok); } .dot.watch { background: var(--watch); }
    .dot.alert { background: var(--alert); } .dot.unmon { background: var(--unmon); }

    .organ-node { cursor: pointer; transition: r 120ms; }
    .organ-node:hover { stroke: #fff; stroke-width: 2; }
    .organ-node.selected { stroke: #fff; stroke-width: 2.5; }
    .organ-label { font-size: 8px; fill: var(--muted); pointer-events: none; }

    .detail {
      background: var(--panel); border: 1px solid var(--border);
      border-radius: 16px; padding: 22px; min-height: 200px;
    }
    .detail .system { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }
    .detail h2 { margin: 4px 0 6px; font-size: 24px; display: flex; align-items: center; gap: 10px; }
    .detail .badge { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; padding: 4px 10px; border-radius: 999px; }
    .badge.ok { background: rgba(22,196,127,.16); color: var(--ok); }
    .badge.watch { background: rgba(244,197,66,.16); color: var(--watch); }
    .badge.alert { background: rgba(239,79,79,.16); color: var(--alert); }
    .badge.unmon { background: rgba(91,100,120,.2); color: var(--unmon); }
    .detail .summary { font-size: 15px; line-height: 1.55; color: var(--text); margin: 12px 0 18px; }
    .detail h3 { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .07em; margin: 18px 0 10px; }
    .metrics { display: flex; flex-wrap: wrap; gap: 8px; }
    .metric-chip { font-size: 12px; background: var(--panel-2); border: 1px solid var(--border); padding: 6px 11px; border-radius: 8px; color: var(--text); }
    .icd-list { display: grid; gap: 8px; }
    .icd {
      display: flex; align-items: baseline; gap: 12px; padding: 10px 12px;
      background: var(--panel-2); border: 1px solid var(--border);
      border-left: 3px solid var(--border); border-radius: 8px;
    }
    .icd.flagged { border-left-color: var(--alert); background: rgba(239,79,79,.08); }
    .icd code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 700; color: var(--accent); font-size: 13px; min-width: 64px; }
    .icd.flagged code { color: var(--alert); }
    .icd .name { font-size: 13px; color: var(--text); }
    .icd .flag-tag { margin-left: auto; font-size: 10px; font-weight: 700; color: var(--alert); text-transform: uppercase; letter-spacing: .05em; }
    .placeholder { color: var(--muted); font-size: 14px; text-align: center; padding: 50px 10px; }
    .disclaimer { color: var(--muted); font-size: 12px; line-height: 1.5; margin-top: 18px; padding: 14px; border: 1px dashed var(--border); border-radius: 10px; }
    footer { color: var(--muted); font-size: 12px; padding: 0 32px 40px; max-width: 1200px; margin: 0 auto; }
    @media (max-width: 820px) {
      header, main { padding-left: 16px; padding-right: 16px; }
      .layout { grid-template-columns: 1fr; }
      .figure-card { position: static; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Body Map &middot; ICD-10 Health Profile</h1>
      <div class="meta" id="meta">Loading…</div>
    </div>
    <div class="range" id="range">
      <button data-days="30">30d</button>
      <button data-days="90" class="active">90d</button>
      <button data-days="180">180d</button>
      <button data-days="365">1y</button>
    </div>
  </header>
  <main>
    <div class="status-banner" id="banner" style="display:none;">
      <h2 id="banner-headline"></h2>
      <div class="pills" id="banner-pills"></div>
    </div>
    <div class="layout">
      <div class="figure-card">
        <svg id="figure" viewBox="0 0 200 420" width="100%" aria-label="Human body figure">
          <!-- body silhouette -->
          <g fill="#1b2030" stroke="#2c3445" stroke-width="1.5">
            <circle cx="100" cy="34" r="26" />
            <rect x="92" y="58" width="16" height="14" rx="4" />
            <path d="M70 74 Q100 66 130 74 L138 180 Q138 210 128 244 L120 250 L80 250 L72 244 Q62 210 62 180 Z" />
            <!-- arms -->
            <path d="M70 78 L48 96 L40 170 L50 172 L60 104 Z" />
            <path d="M130 78 L152 96 L160 170 L150 172 L140 104 Z" />
            <!-- legs -->
            <path d="M82 250 L78 340 L74 400 L88 400 L94 342 L100 300 Z" />
            <path d="M118 250 L122 340 L126 400 L112 400 L106 342 L100 300 Z" />
          </g>
          <g id="organs"></g>
          <g id="organ-labels"></g>
        </svg>
        <div class="legend">
          <span><i class="dot ok"></i> Healthy</span>
          <span><i class="dot watch"></i> Watch</span>
          <span><i class="dot alert"></i> Alert</span>
          <span><i class="dot unmon"></i> Not monitored</span>
        </div>
      </div>
      <div class="detail" id="detail">
        <div class="placeholder">Select an organ on the figure to see its health
          status and linked ICD-10 codes.</div>
      </div>
    </div>
  </main>
  <footer>
    <a href="/dashboard">&larr; Full dashboard</a> ·
    <a href="/api/body?days=90">/api/body</a> ·
    <a href="/api/insights?days=90">/api/insights</a>
  </footer>

  <script>
    const COLOR = { ok: '#16c47f', watch: '#f4c542', alert: '#ef4f4f', unmonitored: '#5b6478' };
    const SVGNS = 'http://www.w3.org/2000/svg';
    let currentDays = 90;
    let data = null;
    let selectedId = null;

    function el(tag, attrs, text) {
      const node = document.createElementNS(SVGNS, tag);
      for (const k in attrs) node.setAttribute(k, attrs[k]);
      if (text != null) node.textContent = text;
      return node;
    }

    function renderFigure(organs) {
      const g = document.getElementById('organs');
      const labels = document.getElementById('organ-labels');
      g.innerHTML = ''; labels.innerHTML = '';
      organs.forEach((o) => {
        const c = el('circle', {
          cx: o.x, cy: o.y, r: 9,
          fill: COLOR[o.status] || COLOR.unmonitored,
          'fill-opacity': o.status === 'unmonitored' ? 0.5 : 0.9,
          stroke: '#0b0d12', 'stroke-width': 1.5,
          class: 'organ-node' + (o.id === selectedId ? ' selected' : ''),
        });
        c.dataset.id = o.id;
        c.addEventListener('click', () => select(o.id));
        g.appendChild(c);
        const lbl = el('text', {
          x: o.x, y: o.y - 12, 'text-anchor': 'middle', class: 'organ-label',
        }, o.name);
        labels.appendChild(lbl);
      });
    }

    const STATUS_LABEL = { ok: 'Healthy', watch: 'Watch', alert: 'Alert', unmonitored: 'Not monitored' };

    function renderDetail(o) {
      const d = document.getElementById('detail');
      if (!o) {
        d.innerHTML = '<div class="placeholder">Select an organ on the figure to see its health status and linked ICD-10 codes.</div>';
        return;
      }
      const flaggedCodes = new Set((o.flagged || []).map((f) => f.code));
      const icdRows = o.icd10.map((c) => {
        const isFlagged = flaggedCodes.has(c.code);
        return `<div class="icd ${isFlagged ? 'flagged' : ''}">
            <code>${c.code}</code><span class="name">${c.name}</span>
            ${isFlagged ? '<span class="flag-tag">flagged</span>' : ''}
          </div>`;
      }).join('');
      const metrics = (o.metrics || []).map((m) => `<span class="metric-chip">${m}</span>`).join('');
      d.innerHTML = `
        <div class="system">${o.system}</div>
        <h2>${o.name} <span class="badge ${o.status}">${STATUS_LABEL[o.status] || o.status}</span></h2>
        <div class="summary">${o.summary}</div>
        <h3>Signals used</h3>
        <div class="metrics">${metrics}</div>
        <h3>Linked ICD-10 codes ${o.flagged && o.flagged.length ? `· ${o.flagged.length} flagged` : ''}</h3>
        <div class="icd-list">${icdRows}</div>
        <div class="disclaimer">${data.disclaimer}</div>`;
    }

    function select(id) {
      selectedId = id;
      document.querySelectorAll('.organ-node').forEach((n) => {
        n.classList.toggle('selected', n.dataset.id === id);
      });
      const o = data.organs.find((x) => x.id === id);
      renderDetail(o);
    }

    function renderBanner(s) {
      const b = document.getElementById('banner');
      b.style.display = '';
      b.className = 'status-banner ' + s.overall.level;
      document.getElementById('banner-headline').textContent = s.overall.headline;
      const c = s.overall.counts;
      const pills = [];
      if (c.alert) pills.push(`<span class="pill alert">${c.alert} alert</span>`);
      if (c.watch) pills.push(`<span class="pill watch">${c.watch} watch</span>`);
      if (c.ok) pills.push(`<span class="pill ok">${c.ok} healthy</span>`);
      if (c.unmonitored) pills.push(`<span class="pill unmon">${c.unmonitored} not monitored</span>`);
      document.getElementById('banner-pills').innerHTML = pills.join('');
    }

    async function load(days) {
      currentDays = days;
      const meta = document.getElementById('meta');
      meta.textContent = 'Loading…';
      try {
        const resp = await fetch(`/api/body?days=${days}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        data = await resp.json();
        const name = data.profile && data.profile.name ? data.profile.name : 'You';
        meta.textContent = `${name} · last ${data.days} days · ${data.organs.length} systems profiled`;
        renderBanner(data);
        renderFigure(data.organs);
        // Keep selection if still present, else auto-select the most severe organ.
        const keep = selectedId && data.organs.find((o) => o.id === selectedId);
        select(keep ? selectedId : data.organs[0].id);
      } catch (err) {
        meta.innerHTML = `<span style="color:var(--alert)">Failed to load: ${err.message}</span>`;
      }
    }

    document.getElementById('range').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-days]');
      if (!btn) return;
      document.querySelectorAll('#range button').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      load(Number(btn.dataset.days));
    });

    load(90);
  </script>
</body>
</html>
"""
