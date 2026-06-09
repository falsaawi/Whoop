"""Dashboard page summarising stored Whoop data.

Routes:
- ``GET /api/summary?days=N``  — legacy aggregated JSON (kept for compatibility).
- ``GET /api/insights?days=N`` — full analysis: baselines, trends, records and
  rule-based recommendations (see :mod:`app.insights`).
- ``GET /dashboard``           — self-contained HTML app rendering the insights
  with Chart.js from a CDN. No templating engine or static mount required.
"""
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.insights import compute_insights
from app.summary import compute_summary

router = APIRouter(tags=["dashboard"])

# Vercel's edge CDN honours s-maxage and purges on every deployment.
# stale-while-revalidate serves the cached copy instantly while refreshing in
# the background, hiding both serverless cold starts and DB wake-ups.
# Data only changes on the daily cron or a manual sync (which cache-busts).
_DATA_CACHE = "public, s-maxage=600, stale-while-revalidate=86400"
_PAGE_CACHE = "public, s-maxage=86400, stale-while-revalidate=604800"


@router.get("/api/summary")
def api_summary(
    response: Response,
    days: int = Query(30, ge=1, le=3650),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = _DATA_CACHE
    return compute_summary(db, days=days)


@router.get("/api/insights")
def api_insights(
    response: Response,
    days: int = Query(90, ge=7, le=3650),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = _DATA_CACHE
    return compute_insights(db, days=days)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    return HTMLResponse(_PAGE, headers={"Cache-Control": _PAGE_CACHE})


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Whoop Health Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #0b0d12; --panel: #141821; --panel-2: #1b2030; --border: #232a3a;
      --text: #e7ebf3; --muted: #8a93a6; --accent: #4cd3a5;
      --green: #16c47f; --yellow: #f4c542; --red: #ef4f4f;
      --blue: #5aa7ff; --purple: #b58cff;
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0; padding: 0; background: var(--bg); color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif;
      -webkit-font-smoothing: antialiased;
    }
    a { color: var(--accent); text-decoration: none; }
    header {
      padding: 28px 32px 16px; display: flex; flex-wrap: wrap;
      align-items: flex-end; gap: 16px; justify-content: space-between;
      border-bottom: 1px solid var(--border);
    }
    header h1 { margin: 0; font-size: 26px; letter-spacing: -0.02em; }
    header .meta { color: var(--muted); font-size: 14px; margin-top: 6px; }
    .controls { display: flex; gap: 10px; align-items: center; }
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
    #sync-btn {
      background: var(--panel); border: 1px solid var(--border);
      color: var(--accent); padding: 11px 16px; border-radius: 10px;
      font-size: 13px; font-weight: 600; cursor: pointer;
    }
    #sync-btn:disabled { color: var(--muted); cursor: wait; }
    main { padding: 24px 32px 48px; max-width: 1400px; margin: 0 auto; }

    /* hero */
    .hero {
      display: grid; grid-template-columns: 280px 1fr; gap: 16px;
      margin-bottom: 20px;
    }
    .status-card {
      border-radius: 14px; padding: 22px; border: 1px solid var(--border);
      background: var(--panel); position: relative; overflow: hidden;
    }
    .status-card.green { border-color: rgba(22,196,127,.5); background: linear-gradient(160deg, rgba(22,196,127,.14), var(--panel) 55%); }
    .status-card.yellow { border-color: rgba(244,197,66,.5); background: linear-gradient(160deg, rgba(244,197,66,.12), var(--panel) 55%); }
    .status-card.red { border-color: rgba(239,79,79,.5); background: linear-gradient(160deg, rgba(239,79,79,.14), var(--panel) 55%); }
    .status-card .label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }
    .status-card h2 { margin: 8px 0 8px; font-size: 22px; letter-spacing: -0.01em; }
    .status-card p { margin: 0; color: var(--muted); font-size: 14px; line-height: 1.5; }
    .gauge-wrap { position: relative; height: 130px; margin-top: 14px; }
    .gauge-center {
      position: absolute; inset: 0; display: flex; flex-direction: column;
      align-items: center; justify-content: center; pointer-events: none;
    }
    .gauge-center .big { font-size: 30px; font-weight: 800; }
    .gauge-center .small { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }

    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; align-content: start; }
    .stat { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 14px 16px; }
    .stat .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
    .stat .value { font-size: 24px; font-weight: 700; margin-top: 5px; letter-spacing: -0.02em; }
    .stat .unit { font-size: 13px; color: var(--muted); margin-left: 3px; font-weight: 500; }
    .stat .delta { font-size: 12px; margin-top: 3px; font-weight: 600; }
    .delta.up { color: var(--green); } .delta.down { color: var(--red); } .delta.flat { color: var(--muted); }
    .stat.green .value { color: var(--green); } .stat.yellow .value { color: var(--yellow); }
    .stat.red .value { color: var(--red); } .stat.blue .value { color: var(--blue); }
    .stat.purple .value { color: var(--purple); }

    section h3 {
      font-size: 13px; color: var(--muted); text-transform: uppercase;
      letter-spacing: .08em; margin: 26px 0 12px; font-weight: 700;
    }
    /* recommendations */
    .recs { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
    .rec {
      background: var(--panel); border: 1px solid var(--border);
      border-left: 4px solid var(--muted); border-radius: 12px; padding: 14px 16px;
    }
    .rec.high { border-left-color: var(--red); }
    .rec.medium { border-left-color: var(--yellow); }
    .rec.low { border-left-color: var(--blue); }
    .rec.positive { border-left-color: var(--green); }
    .rec .tag { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }
    .rec.high .tag { color: var(--red); } .rec.medium .tag { color: var(--yellow); }
    .rec.low .tag { color: var(--blue); } .rec.positive .tag { color: var(--green); }
    .rec h4 { margin: 6px 0; font-size: 15px; }
    .rec p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.5; }

    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 16px; }
    .card { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 18px; }
    .card h2 { font-size: 13px; margin: 0 0 12px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }
    .card .chart-wrap { position: relative; height: 220px; }
    .card.wide { grid-column: 1 / -1; }

    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }
    th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }
    tr:last-child td { border-bottom: none; }
    td.num { text-align: right; font-variant-numeric: tabular-nums; }

    .records { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
    .record { background: var(--panel-2); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }
    .record .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }
    .record .value { font-size: 20px; font-weight: 700; margin-top: 4px; color: var(--accent); }
    .record .when { font-size: 12px; color: var(--muted); margin-top: 2px; }

    .empty {
      padding: 60px 20px; text-align: center; color: var(--muted);
      background: var(--panel); border: 1px dashed var(--border); border-radius: 14px;
    }
    .empty code { background: var(--panel-2); padding: 2px 6px; border-radius: 4px; color: var(--accent); }
    .loading { display: inline-block; color: var(--muted); font-size: 14px; }
    footer { color: var(--muted); font-size: 12px; padding: 0 32px 40px; max-width: 1400px; margin: 0 auto; }
    @media (max-width: 800px) {
      header, main { padding-left: 16px; padding-right: 16px; }
      .hero { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Whoop Health Dashboard</h1>
      <div class="meta" id="meta">Loading…</div>
    </div>
    <div class="controls">
      <div class="range" id="range">
        <button data-days="30">30d</button>
        <button data-days="90" class="active">90d</button>
        <button data-days="180">180d</button>
        <button data-days="365">1y</button>
      </div>
      <button id="sync-btn" title="Pull the latest data from Whoop">&#x21bb; Sync now</button>
    </div>
  </header>
  <main id="main">
    <div class="hero" id="hero" style="display:none;">
      <div class="status-card" id="status-card">
        <div class="label">Current status</div>
        <h2 id="status-headline"></h2>
        <p id="status-detail"></p>
        <div class="gauge-wrap">
          <canvas id="gauge"></canvas>
          <div class="gauge-center">
            <div class="big" id="gauge-value">–</div>
            <div class="small">recovery</div>
          </div>
        </div>
      </div>
      <div class="stats" id="today-stats"></div>
    </div>

    <section id="recs-section" style="display:none;">
      <h3>Recommendations</h3>
      <div class="recs" id="recs"></div>
    </section>

    <section id="trends-section" style="display:none;">
      <h3>Trends (dots = daily, line = 7-day average)</h3>
      <div class="grid" id="trend-charts"></div>
    </section>

    <section id="training-section" style="display:none;">
      <h3>Training analysis</h3>
      <div class="grid" id="training-charts"></div>
    </section>

    <section id="records-section" style="display:none;">
      <h3>Personal records in this window</h3>
      <div class="records" id="records"></div>
    </section>

    <section class="card wide" id="workouts-card" style="margin-top:24px; display:none;">
      <h2>Recent workouts</h2>
      <table id="workouts-table">
        <thead>
          <tr>
            <th>Date</th><th>Sport</th><th class="num">Strain</th>
            <th class="num">Duration</th><th class="num">Avg HR</th>
            <th class="num">Max HR</th><th class="num">kJ</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </section>
  </main>
  <footer>
    Raw data: <a href="/recovery">/recovery</a> · <a href="/sleep">/sleep</a> ·
    <a href="/workouts">/workouts</a> · <a href="/cycles">/cycles</a> ·
    <a href="/api/insights?days=90">/api/insights</a> ·
    <a href="/sync/history">/sync/history</a> · <a href="/health">/health</a>
  </footer>

  <script>
    const COLORS = {
      green: '#16c47f', yellow: '#f4c542', red: '#ef4f4f', blue: '#5aa7ff',
      purple: '#b58cff', muted: '#8a93a6', grid: 'rgba(255,255,255,0.06)',
    };
    Chart.defaults.color = COLORS.muted;
    Chart.defaults.borderColor = COLORS.grid;
    Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    const charts = {};
    let currentDays = 90;

    function fmt(v, digits = 1) {
      if (v === null || v === undefined || Number.isNaN(v)) return '—';
      return Number(v).toFixed(digits);
    }
    function fmtInt(v) {
      if (v === null || v === undefined) return '—';
      return Math.round(Number(v)).toLocaleString();
    }
    function fmtDate(iso) {
      if (!iso) return '—';
      return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }
    function fmtDateTime(iso) {
      if (!iso) return '—';
      return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }
    function ensureChart(key, canvasId, config) {
      if (charts[key]) charts[key].destroy();
      const el = document.getElementById(canvasId);
      if (!el) return;
      charts[key] = new Chart(el.getContext('2d'), config);
    }
    function chartCard(id, title) {
      return `<div class="card"><h2>${title}</h2><div class="chart-wrap"><canvas id="${id}"></canvas></div></div>`;
    }

    /* ---------- hero ---------- */
    function deltaBadge(value, baselineMean, goodWhenHigh, unit) {
      if (value === null || value === undefined || !baselineMean) return '';
      const pct = (value - baselineMean) / Math.abs(baselineMean) * 100;
      if (Math.abs(pct) < 2) return `<div class="delta flat">&#8596; on baseline</div>`;
      const better = (pct > 0) === goodWhenHigh;
      const arrow = pct > 0 ? '&#8593;' : '&#8595;';
      return `<div class="delta ${better ? 'up' : 'down'}">${arrow} ${Math.abs(pct).toFixed(0)}% vs avg</div>`;
    }
    function statCard(label, value, unit, klass, delta) {
      return `<div class="stat ${klass || ''}">
        <div class="label">${label}</div>
        <div class="value">${value}<span class="unit">${unit || ''}</span></div>
        ${delta || ''}
      </div>`;
    }
    function renderHero(s) {
      document.getElementById('hero').style.display = '';
      const cur = s.current, b = s.baselines, o = s.overall;
      const card = document.getElementById('status-card');
      card.className = 'status-card ' + (o.level || '');
      document.getElementById('status-headline').textContent = o.headline;
      document.getElementById('status-detail').textContent = o.detail +
        (cur.date ? ` (latest data: ${fmtDate(cur.date)})` : '');

      const rec = cur.recovery;
      document.getElementById('gauge-value').textContent = rec === null || rec === undefined ? '—' : Math.round(rec) + '%';
      const color = cur.recovery_bucket === 'green' ? COLORS.green : cur.recovery_bucket === 'red' ? COLORS.red : COLORS.yellow;
      ensureChart('gauge', 'gauge', {
        type: 'doughnut',
        data: { datasets: [{ data: [rec || 0, 100 - (rec || 0)], backgroundColor: [color, '#1b2030'], borderWidth: 0 }] },
        options: { cutout: '78%', responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { enabled: false } } },
      });

      document.getElementById('today-stats').innerHTML = [
        statCard('Latest strain', fmt(cur.strain, 1), '', 'blue',
          deltaBadge(cur.strain, b.strain.mean, false)),
        statCard('HRV', fmt(cur.hrv, 0), 'ms', 'green',
          deltaBadge(cur.hrv, b.hrv.mean, true)),
        statCard('Resting HR', fmt(cur.rhr, 0), 'bpm', 'red',
          deltaBadge(cur.rhr, b.rhr.mean, false)),
        statCard('Last sleep', fmt(cur.sleep_hours, 1), 'h', 'purple',
          deltaBadge(cur.sleep_hours, b.sleep_hours.mean, true)),
        statCard('Sleep score', fmt(cur.sleep_performance, 0), '%', 'purple'),
        statCard('SpO2', fmt(cur.spo2, 1), '%', ''),
        statCard('Avg recovery', fmt(s.averages.recovery_score, 0), '%',
          (s.averages.recovery_score >= 67 ? 'green' : s.averages.recovery_score >= 34 ? 'yellow' : 'red')),
        statCard('Avg sleep', fmt(s.averages.sleep_hours, 1), 'h', 'purple'),
      ].join('');
    }

    /* ---------- recommendations ---------- */
    const PRIORITY_LABEL = { high: 'Act now', medium: 'Worth improving', low: 'Minor', positive: 'Going well' };
    function renderRecs(s) {
      const wrap = document.getElementById('recs-section');
      wrap.style.display = '';
      document.getElementById('recs').innerHTML = (s.recommendations || [])
        .map((r) => `<div class="rec ${r.priority}">
            <span class="tag">${PRIORITY_LABEL[r.priority] || r.priority} · ${r.category}</span>
            <h4>${r.title}</h4><p>${r.detail}</p>
          </div>`)
        .join('');
    }

    /* ---------- trend charts ---------- */
    function trendConfig(label, color, daily, ma) {
      return {
        type: 'line',
        data: { datasets: [
          { label: label + ' (7d avg)', data: ma.map((p) => ({ x: p.t, y: p.v })),
            borderColor: color, backgroundColor: color + '22', borderWidth: 2,
            pointRadius: 0, tension: 0.35, fill: true },
          { label, data: daily.map((p) => ({ x: p.t, y: p.v })),
            borderColor: 'transparent', backgroundColor: color + '55',
            pointRadius: 2, pointHoverRadius: 4, showLine: false },
        ]},
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { mode: 'nearest', intersect: false },
          plugins: { legend: { display: false },
            tooltip: { backgroundColor: '#1b2030', borderColor: '#232a3a', borderWidth: 1,
              callbacks: { title: (items) => fmtDate(items[0].parsed.x),
                           label: (item) => `${item.dataset.label}: ${fmt(item.parsed.y, 1)}` } } },
          scales: {
            x: { type: 'time', time: { unit: 'day' }, grid: { color: COLORS.grid }, ticks: { maxTicksLimit: 6 } },
            y: { grid: { color: COLORS.grid }, ticks: { precision: 0 } },
          },
        },
      };
    }
    function renderTrends(s) {
      document.getElementById('trends-section').style.display = '';
      document.getElementById('trend-charts').innerHTML = [
        chartCard('c-recovery', 'Recovery score'),
        chartCard('c-hrv', 'HRV (rMSSD, ms)'),
        chartCard('c-rhr', 'Resting heart rate (bpm)'),
        chartCard('c-strain', 'Day strain'),
        chartCard('c-sleep-h', 'Sleep duration (hours)'),
        chartCard('c-sleep-p', 'Sleep performance (%)'),
      ].join('');
      ensureChart('recovery', 'c-recovery', trendConfig('Recovery', COLORS.green, s.series.recovery, s.series_ma7.recovery));
      ensureChart('hrv', 'c-hrv', trendConfig('HRV', COLORS.blue, s.series.hrv, s.series_ma7.hrv));
      ensureChart('rhr', 'c-rhr', trendConfig('RHR', COLORS.red, s.series.rhr, s.series_ma7.rhr));
      ensureChart('strain', 'c-strain', trendConfig('Strain', COLORS.blue, s.series.strain, s.series_ma7.strain));
      ensureChart('sleep-h', 'c-sleep-h', trendConfig('Hours', COLORS.purple, s.series.sleep_hours, s.series_ma7.sleep_hours));
      ensureChart('sleep-p', 'c-sleep-p', trendConfig('Sleep %', COLORS.purple, s.series.sleep_performance, s.series_ma7.sleep_performance));
    }

    /* ---------- training ---------- */
    function renderTraining(s) {
      document.getElementById('training-section').style.display = '';
      document.getElementById('training-charts').innerHTML = [
        chartCard('c-weekly', 'Weekly training volume (minutes)'),
        chartCard('c-scatter', 'Strain vs recovery (each dot = a day)'),
        chartCard('c-dist', 'Recovery distribution'),
        chartCard('c-sports', 'Training time by sport (minutes)'),
      ].join('');

      const weekly = s.training_analysis.weekly || [];
      ensureChart('weekly', 'c-weekly', {
        type: 'bar',
        data: { labels: weekly.map((w) => fmtDate(w.week)),
          datasets: [{ label: 'Minutes', data: weekly.map((w) => w.minutes),
            backgroundColor: COLORS.blue + 'aa', borderRadius: 4 }] },
        options: { responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false },
            tooltip: { callbacks: { afterLabel: (i) => `${weekly[i.dataIndex].workouts} workout(s)` } } },
          scales: { x: { grid: { display: false } }, y: { grid: { color: COLORS.grid } } } },
      });

      const pts = s.scatter || [];
      ensureChart('scatter', 'c-scatter', {
        type: 'scatter',
        data: { datasets: [{
          data: pts.map((p) => ({ x: p.recovery, y: p.strain })),
          backgroundColor: pts.map((p) => p.recovery >= 67 ? COLORS.green + 'cc' : p.recovery >= 34 ? COLORS.yellow + 'cc' : COLORS.red + 'cc'),
          pointRadius: 4 }] },
        options: { responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false },
            tooltip: { callbacks: { label: (i) => `Recovery ${fmt(i.parsed.x,0)}% / Strain ${fmt(i.parsed.y,1)}` } } },
          scales: {
            x: { title: { display: true, text: 'Recovery %' }, min: 0, max: 100, grid: { color: COLORS.grid } },
            y: { title: { display: true, text: 'Day strain' }, grid: { color: COLORS.grid } },
          } },
      });

      const dist = s.recovery_distribution;
      ensureChart('dist', 'c-dist', {
        type: 'doughnut',
        data: { labels: ['Green (67+)', 'Yellow (34-66)', 'Red (<34)'],
          datasets: [{ data: [dist.green, dist.yellow, dist.red],
            backgroundColor: [COLORS.green, COLORS.yellow, COLORS.red],
            borderColor: '#141821', borderWidth: 2 }] },
        options: { responsive: true, maintainAspectRatio: false, cutout: '65%',
          plugins: { legend: { position: 'right', labels: { color: '#e7ebf3', boxWidth: 12 } } } },
      });

      const sports = s.workout_minutes_by_sport || {};
      const labels = Object.keys(sports);
      const palette = [COLORS.blue, COLORS.green, COLORS.purple, COLORS.yellow, COLORS.red, '#4cd3a5', '#ff8c5a', '#5ad6ff', '#c0a8ff'];
      ensureChart('sports', 'c-sports', {
        type: 'doughnut',
        data: { labels: labels.length ? labels : ['No workouts'],
          datasets: [{ data: labels.length ? labels.map((k) => sports[k]) : [1],
            backgroundColor: labels.length ? labels.map((_, i) => palette[i % palette.length]) : [COLORS.muted],
            borderColor: '#141821', borderWidth: 2 }] },
        options: { responsive: true, maintainAspectRatio: false, cutout: '65%',
          plugins: { legend: { position: 'right', labels: { color: '#e7ebf3', boxWidth: 12 } } } },
      });
    }

    /* ---------- records & workouts ---------- */
    function recordCard(label, value, when) {
      return `<div class="record"><div class="label">${label}</div>
        <div class="value">${value}</div><div class="when">${when}</div></div>`;
    }
    function renderRecords(s) {
      const r = s.records || {};
      const cards = [];
      if (r.best_recovery) cards.push(recordCard('Best recovery', fmt(r.best_recovery.v, 0) + '%', fmtDate(r.best_recovery.t)));
      if (r.best_hrv) cards.push(recordCard('Highest HRV', fmt(r.best_hrv.v, 0) + ' ms', fmtDate(r.best_hrv.t)));
      if (r.lowest_rhr) cards.push(recordCard('Lowest resting HR', fmt(r.lowest_rhr.v, 0) + ' bpm', fmtDate(r.lowest_rhr.t)));
      if (r.max_strain) cards.push(recordCard('Biggest day strain', fmt(r.max_strain.v, 1), fmtDate(r.max_strain.t)));
      if (r.longest_sleep) cards.push(recordCard('Longest sleep', fmt(r.longest_sleep.v, 1) + ' h', fmtDate(r.longest_sleep.t)));
      cards.push(recordCard('Total training', fmt((s.totals.workout_minutes || 0) / 60, 1) + ' h', `${s.counts.workouts} workouts`));
      if (!cards.length) return;
      document.getElementById('records-section').style.display = '';
      document.getElementById('records').innerHTML = cards.join('');
    }
    function renderWorkouts(s) {
      const card = document.getElementById('workouts-card');
      const rows = s.recent_workouts || [];
      if (!rows.length) { card.style.display = 'none'; return; }
      card.style.display = '';
      document.querySelector('#workouts-table tbody').innerHTML = rows.map((w) => `<tr>
          <td>${fmtDateTime(w.start)}</td><td>${w.sport || '—'}</td>
          <td class="num">${fmt(w.strain, 1)}</td>
          <td class="num">${fmt(w.duration_minutes, 0)} min</td>
          <td class="num">${fmtInt(w.average_heart_rate)}</td>
          <td class="num">${fmtInt(w.max_heart_rate)}</td>
          <td class="num">${fmtInt(w.kilojoule)}</td>
        </tr>`).join('');
    }

    /* ---------- load ---------- */
    async function load(days, bustCache) {
      currentDays = days;
      const meta = document.getElementById('meta');
      meta.innerHTML = '<span class="loading">Loading…</span>';
      try {
        const url = `/api/insights?days=${days}` + (bustCache ? `&_=${Date.now()}` : '');
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const s = await resp.json();
        const name = s.profile && s.profile.name ? s.profile.name : 'You';
        meta.textContent = `${name} · last ${s.days} days · ${s.counts.cycles} days of data · ${s.counts.workouts} workouts`;
        if (!s.counts.cycles && !s.counts.sleeps && !s.counts.workouts) {
          document.getElementById('main').innerHTML = `<div class="empty">
            <p>No Whoop data in the selected window.</p>
            <p>Try a wider range, or hit "Sync now" to pull your data.</p></div>`;
          return;
        }
        renderHero(s); renderRecs(s); renderTrends(s);
        renderTraining(s); renderRecords(s); renderWorkouts(s);
      } catch (err) {
        meta.innerHTML = `<span style="color: var(--red)">Failed to load: ${err.message}</span>`;
      }
    }

    document.getElementById('range').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-days]');
      if (!btn) return;
      document.querySelectorAll('#range button').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      load(Number(btn.dataset.days));
    });

    document.getElementById('sync-btn').addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true; btn.textContent = 'Syncing… (can take a minute)';
      try {
        const resp = await fetch('/sync', { method: 'POST' });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        await load(currentDays, true);
        btn.textContent = '✓ Synced';
      } catch (err) {
        btn.textContent = 'Sync failed — retry';
      } finally {
        btn.disabled = false;
        setTimeout(() => { btn.innerHTML = '&#x21bb; Sync now'; }, 4000);
      }
    });

    load(90);
  </script>
</body>
</html>
"""
