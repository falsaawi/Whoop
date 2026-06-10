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

    #figure { display: block; margin: 0 auto; max-height: 560px; }
    .organ-hit { cursor: pointer; fill: transparent; }
    .organ-node { pointer-events: none; transition: opacity 120ms; }
    .organ-ring { pointer-events: none; }
    .organ-hit:hover + .organ-node { stroke: #fff; stroke-width: 2; }
    .organ-dot.selected { stroke: #fff; stroke-width: 2.5; }
    .organ-pulse { transform-box: fill-box; transform-origin: center;
      animation: pulse 1.8s ease-out infinite; }
    @keyframes pulse {
      0% { transform: scale(0.8); opacity: 0.55; }
      70% { transform: scale(2.2); opacity: 0; }
      100% { opacity: 0; }
    }
    .organ-label { font-size: 9px; font-weight: 600; fill: #cfd6e4;
      pointer-events: none; paint-order: stroke; stroke: #0b0d12;
      stroke-width: 2.6px; stroke-linejoin: round; }
    .organ-label.dim { fill: var(--muted); }

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
        <svg id="figure" viewBox="0 0 240 520" width="100%" aria-label="Human body figure">
          <defs>
            <linearGradient id="bodyGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stop-color="#283246" />
              <stop offset="0.55" stop-color="#1d2536" />
              <stop offset="1" stop-color="#161c29" />
            </linearGradient>
            <radialGradient id="bodyHi" cx="0.5" cy="0.32" r="0.7">
              <stop offset="0" stop-color="#3a486a" stop-opacity="0.55" />
              <stop offset="1" stop-color="#3a486a" stop-opacity="0" />
            </radialGradient>
            <filter id="nodeGlow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="3" result="b" />
              <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          <!-- body silhouette: head, neck, torso, arms, legs -->
          <g fill="url(#bodyGrad)" stroke="#3a4763" stroke-width="1.4"
             stroke-linejoin="round">
            <!-- head -->
            <path d="M120 12
                     C 136 12 149 27 149 46
                     C 149 62 140 75 120 78
                     C 100 75 91 62 91 46
                     C 91 27 104 12 120 12 Z" />
            <!-- neck -->
            <path d="M110 72 L110 92 Q120 98 130 92 L130 72 Z" />
            <!-- torso -->
            <path d="M86 96
                     Q120 86 154 96
                     Q168 102 170 116
                     L162 152 Q159 168 156 186
                     L152 230 Q150 258 142 286
                     Q121 296 98 286
                     Q90 258 88 230
                     L84 186 Q81 168 78 152
                     L70 116 Q72 102 86 96 Z" />
            <!-- left arm -->
            <path d="M84 100 Q66 106 60 124 L46 206 Q43 232 48 258
                     L60 258 Q60 232 64 206 L76 134 Q78 116 88 110 Z" />
            <!-- right arm -->
            <path d="M156 100 Q174 106 180 124 L194 206 Q197 232 192 258
                     L180 258 Q180 232 176 206 L164 134 Q162 116 152 110 Z" />
            <!-- left leg -->
            <path d="M118 290 L116 300 Q100 308 96 300 L98 290
                     Q92 360 88 420 L82 506 L102 506 L108 420
                     Q112 360 116 308 Z" />
            <!-- right leg -->
            <path d="M122 290 L124 300 Q140 308 144 300 L142 290
                     Q148 360 152 420 L158 506 L138 506 L132 420
                     Q128 360 124 308 Z" />
          </g>

          <!-- soft top highlight + faint anatomical centre line -->
          <ellipse cx="120" cy="150" rx="78" ry="120" fill="url(#bodyHi)" />
          <line x1="120" y1="100" x2="120" y2="286" stroke="#46557a"
                stroke-width="0.8" stroke-opacity="0.4" stroke-dasharray="2 4" />

          <g id="organ-links"></g>
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

    // Labels sit left or right of the node so they don't collide with the body.
    const LABEL_SIDE = {
      brain: 'top', airway: 'right', lungs: 'left', heart: 'right',
      immune: 'left', liver: 'left', stomach: 'right', kidneys: 'right',
      skin: 'right', muscles: 'left',
    };

    function renderFigure(organs) {
      const g = document.getElementById('organs');
      const labels = document.getElementById('organ-labels');
      g.innerHTML = ''; labels.innerHTML = '';
      organs.forEach((o) => {
        const color = COLOR[o.status] || COLOR.unmonitored;
        const node = el('g', { class: 'organ-node' });

        // soft glow halo
        node.appendChild(el('circle', {
          cx: o.x, cy: o.y, r: 11, fill: color,
          'fill-opacity': o.status === 'unmonitored' ? 0.12 : 0.22,
          filter: 'url(#nodeGlow)', class: 'organ-ring',
        }));
        // pulsing ring for organs that need attention
        if (o.status === 'alert' || o.status === 'watch') {
          node.appendChild(el('circle', {
            cx: o.x, cy: o.y, r: 8, fill: 'none', stroke: color,
            'stroke-width': 2, class: 'organ-pulse',
          }));
        }
        // the dot
        node.appendChild(el('circle', {
          cx: o.x, cy: o.y, r: 7.5, fill: color,
          'fill-opacity': o.status === 'unmonitored' ? 0.55 : 1,
          stroke: '#0b0d12', 'stroke-width': 1.6,
          class: 'organ-dot' + (o.id === selectedId ? ' selected' : ''),
          'data-id': o.id,
        }));
        g.appendChild(node);

        // transparent larger hit target for easy clicking
        const hit = el('circle', { cx: o.x, cy: o.y, r: 13, class: 'organ-hit' });
        hit.dataset.id = o.id;
        hit.addEventListener('click', () => select(o.id));
        g.insertBefore(hit, node);

        // label, offset to a clear side
        const side = LABEL_SIDE[o.id] || 'right';
        let lx = o.x, ly = o.y, anchor = 'middle';
        if (side === 'left') { lx = o.x - 14; anchor = 'end'; ly = o.y + 3; }
        else if (side === 'right') { lx = o.x + 14; anchor = 'start'; ly = o.y + 3; }
        else { ly = o.y - 15; anchor = 'middle'; }
        const lbl = el('text', {
          x: lx, y: ly, 'text-anchor': anchor,
          class: 'organ-label' + (o.status === 'unmonitored' ? ' dim' : ''),
          'data-id': o.id,
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
      document.querySelectorAll('.organ-dot').forEach((n) => {
        n.classList.toggle('selected', n.dataset.id === id);
      });
      document.querySelectorAll('.organ-label').forEach((n) => {
        n.style.fontWeight = n.dataset.id === id ? '800' : '600';
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
