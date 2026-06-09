"""Dashboard page summarising stored Whoop data.

Exposes two routes:
- ``GET /api/summary?days=N`` — aggregated JSON for the last N days.
- ``GET /dashboard`` — self-contained HTML page that renders that data with
  Chart.js (loaded from a CDN). No templating engine or static-files mount
  required.
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.summary import compute_summary

router = APIRouter(tags=["dashboard"])


@router.get("/api/summary")
def api_summary(
    days: int = Query(30, ge=1, le=3650),
    db: Session = Depends(get_db),
):
    return compute_summary(db, days=days)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    return HTMLResponse(_PAGE)


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Whoop Summary</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #0b0d12;
      --panel: #141821;
      --panel-2: #1b2030;
      --border: #232a3a;
      --text: #e7ebf3;
      --muted: #8a93a6;
      --accent: #4cd3a5;
      --green: #16c47f;
      --yellow: #f4c542;
      --red: #ef4f4f;
      --blue: #5aa7ff;
      --purple: #b58cff;
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      padding: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif;
      -webkit-font-smoothing: antialiased;
    }
    a { color: var(--accent); text-decoration: none; }
    header {
      padding: 32px 32px 16px;
      display: flex;
      flex-wrap: wrap;
      align-items: flex-end;
      gap: 16px;
      justify-content: space-between;
      border-bottom: 1px solid var(--border);
    }
    header h1 {
      margin: 0;
      font-size: 28px;
      letter-spacing: -0.02em;
    }
    header .meta {
      color: var(--muted);
      font-size: 14px;
      margin-top: 6px;
    }
    .range {
      display: inline-flex;
      gap: 4px;
      background: var(--panel);
      border: 1px solid var(--border);
      padding: 4px;
      border-radius: 10px;
    }
    .range button {
      background: transparent;
      color: var(--muted);
      border: none;
      padding: 8px 14px;
      font-size: 13px;
      font-weight: 600;
      border-radius: 7px;
      cursor: pointer;
      transition: background 120ms, color 120ms;
    }
    .range button:hover { color: var(--text); }
    .range button.active {
      background: var(--panel-2);
      color: var(--text);
    }
    main {
      padding: 24px 32px 48px;
      max-width: 1400px;
      margin: 0 auto;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .stat {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 16px 18px;
    }
    .stat .label {
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-weight: 600;
    }
    .stat .value {
      font-size: 28px;
      font-weight: 700;
      margin-top: 6px;
      letter-spacing: -0.02em;
    }
    .stat .unit {
      font-size: 14px;
      color: var(--muted);
      margin-left: 4px;
      font-weight: 500;
    }
    .stat.green .value { color: var(--green); }
    .stat.yellow .value { color: var(--yellow); }
    .stat.red .value { color: var(--red); }
    .stat.blue .value { color: var(--blue); }
    .stat.purple .value { color: var(--purple); }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
      gap: 16px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px;
    }
    .card h2 {
      font-size: 14px;
      margin: 0 0 12px;
      color: var(--muted);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .card .chart-wrap {
      position: relative;
      height: 220px;
    }
    .card.wide { grid-column: 1 / -1; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
    }
    th {
      color: var(--muted);
      font-weight: 600;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    tr:last-child td { border-bottom: none; }
    td.num { text-align: right; font-variant-numeric: tabular-nums; }
    .empty {
      padding: 60px 20px;
      text-align: center;
      color: var(--muted);
      background: var(--panel);
      border: 1px dashed var(--border);
      border-radius: 14px;
    }
    .empty code {
      background: var(--panel-2);
      padding: 2px 6px;
      border-radius: 4px;
      color: var(--accent);
    }
    .loading {
      display: inline-block;
      color: var(--muted);
      font-size: 14px;
    }
    @media (max-width: 600px) {
      header, main { padding-left: 16px; padding-right: 16px; }
      header h1 { font-size: 22px; }
      .stat .value { font-size: 22px; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Whoop Summary</h1>
      <div class="meta" id="meta">Loading…</div>
    </div>
    <div class="range" id="range">
      <button data-days="7">7d</button>
      <button data-days="30" class="active">30d</button>
      <button data-days="90">90d</button>
      <button data-days="365">1y</button>
    </div>
  </header>
  <main>
    <section class="stats" id="stats"></section>
    <section class="grid" id="charts"></section>
    <section class="card wide" id="workouts-card" style="margin-top:16px; display:none;">
      <h2>Recent workouts</h2>
      <table id="workouts-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Sport</th>
            <th class="num">Strain</th>
            <th class="num">Duration</th>
            <th class="num">Avg HR</th>
            <th class="num">Max HR</th>
            <th class="num">kJ</th>
          </tr>
        </thead>
        <tbody></tbody>
      </table>
    </section>
  </main>

  <script>
    const COLORS = {
      green: '#16c47f',
      yellow: '#f4c542',
      red: '#ef4f4f',
      blue: '#5aa7ff',
      purple: '#b58cff',
      muted: '#8a93a6',
      grid: 'rgba(255,255,255,0.06)',
    };

    Chart.defaults.color = COLORS.muted;
    Chart.defaults.borderColor = COLORS.grid;
    Chart.defaults.font.family =
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';

    const charts = {};

    function fmt(value, digits = 1) {
      if (value === null || value === undefined || Number.isNaN(value)) return '—';
      return Number(value).toFixed(digits);
    }

    function fmtInt(value) {
      if (value === null || value === undefined) return '—';
      return Math.round(Number(value)).toLocaleString();
    }

    function fmtDate(iso) {
      if (!iso) return '—';
      const d = new Date(iso);
      return d.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
      });
    }

    function fmtDateTime(iso) {
      if (!iso) return '—';
      const d = new Date(iso);
      return d.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    }

    function statCard(label, value, unit, klass) {
      return `<div class="stat ${klass || ''}">
        <div class="label">${label}</div>
        <div class="value">${value}<span class="unit">${unit || ''}</span></div>
      </div>`;
    }

    function bucketForScore(s) {
      if (s === null || s === undefined) return null;
      if (s >= 67) return 'green';
      if (s >= 34) return 'yellow';
      return 'red';
    }

    function renderStats(s) {
      const a = s.averages;
      const c = s.counts;
      const recBucket = bucketForScore(a.recovery_score) || 'blue';
      const stats = document.getElementById('stats');
      stats.innerHTML = [
        statCard('Avg Recovery', fmt(a.recovery_score, 0), '%', recBucket),
        statCard('Avg Strain', fmt(a.strain, 1), '', 'blue'),
        statCard('Avg Sleep', fmt(a.sleep_performance, 0), '%', 'purple'),
        statCard('Avg Sleep Hours', fmt(a.sleep_hours, 1), 'h', 'purple'),
        statCard('Avg HRV', fmt(a.hrv_rmssd_milli, 0), 'ms', 'green'),
        statCard('Avg RHR', fmt(a.resting_heart_rate, 0), 'bpm', 'red'),
        statCard('Workouts', fmtInt(c.workouts), ''),
        statCard('Workout Time', fmt((s.totals.workout_minutes || 0) / 60, 1), 'h'),
      ].join('');
    }

    function lineChartConfig(label, color, series) {
      return {
        type: 'line',
        data: {
          datasets: [
            {
              label,
              data: series.map((p) => ({ x: p.t, y: p.v })),
              borderColor: color,
              backgroundColor: color + '22',
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 4,
              tension: 0.3,
              fill: true,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: '#1b2030',
              borderColor: '#232a3a',
              borderWidth: 1,
              titleColor: '#e7ebf3',
              bodyColor: '#e7ebf3',
              callbacks: {
                title: (items) => fmtDate(items[0].parsed.x),
                label: (item) => `${label}: ${fmt(item.parsed.y, 1)}`,
              },
            },
          },
          scales: {
            x: {
              type: 'time',
              time: { unit: 'day' },
              grid: { color: COLORS.grid },
              ticks: { maxTicksLimit: 6 },
            },
            y: {
              grid: { color: COLORS.grid },
              ticks: { precision: 0 },
            },
          },
        },
      };
    }

    function donutChartConfig(labels, data, colors) {
      return {
        type: 'doughnut',
        data: {
          labels,
          datasets: [
            {
              data,
              backgroundColor: colors,
              borderColor: '#141821',
              borderWidth: 2,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '65%',
          plugins: {
            legend: {
              position: 'right',
              labels: { color: '#e7ebf3', boxWidth: 12, padding: 12 },
            },
            tooltip: {
              backgroundColor: '#1b2030',
              borderColor: '#232a3a',
              borderWidth: 1,
            },
          },
        },
      };
    }

    function ensureChart(key, canvasId, config) {
      if (charts[key]) {
        charts[key].destroy();
      }
      const ctx = document.getElementById(canvasId).getContext('2d');
      charts[key] = new Chart(ctx, config);
    }

    function chartCard(id, title) {
      return `<div class="card">
        <h2>${title}</h2>
        <div class="chart-wrap"><canvas id="${id}"></canvas></div>
      </div>`;
    }

    function renderCharts(s) {
      const container = document.getElementById('charts');
      container.innerHTML = [
        chartCard('chart-recovery', 'Recovery score'),
        chartCard('chart-strain', 'Day strain'),
        chartCard('chart-sleep', 'Sleep performance'),
        chartCard('chart-sleep-hours', 'Sleep duration (hours)'),
        chartCard('chart-hrv', 'HRV (rMSSD, ms)'),
        chartCard('chart-rhr', 'Resting heart rate (bpm)'),
        chartCard('chart-dist', 'Recovery distribution'),
        chartCard('chart-sports', 'Workouts by sport'),
      ].join('');

      ensureChart(
        'recovery',
        'chart-recovery',
        lineChartConfig('Recovery', COLORS.green, s.series.recovery)
      );
      ensureChart(
        'strain',
        'chart-strain',
        lineChartConfig('Strain', COLORS.blue, s.series.strain)
      );
      ensureChart(
        'sleep',
        'chart-sleep',
        lineChartConfig('Sleep %', COLORS.purple, s.series.sleep_performance)
      );
      ensureChart(
        'sleep-hours',
        'chart-sleep-hours',
        lineChartConfig('Hours', COLORS.purple, s.series.sleep_hours)
      );
      ensureChart(
        'hrv',
        'chart-hrv',
        lineChartConfig('HRV', COLORS.green, s.series.hrv)
      );
      ensureChart(
        'rhr',
        'chart-rhr',
        lineChartConfig('RHR', COLORS.red, s.series.rhr)
      );

      const dist = s.recovery_distribution;
      ensureChart(
        'dist',
        'chart-dist',
        donutChartConfig(
          ['Green (67+)', 'Yellow (34-66)', 'Red (<34)'],
          [dist.green, dist.yellow, dist.red],
          [COLORS.green, COLORS.yellow, COLORS.red]
        )
      );

      const sports = s.workouts_by_sport || {};
      const sportLabels = Object.keys(sports);
      const sportData = sportLabels.map((k) => sports[k]);
      const palette = [
        COLORS.blue, COLORS.green, COLORS.purple, COLORS.yellow,
        COLORS.red, '#4cd3a5', '#ff8c5a', '#5ad6ff', '#c0a8ff',
      ];
      const sportColors = sportLabels.map((_, i) => palette[i % palette.length]);
      ensureChart(
        'sports',
        'chart-sports',
        donutChartConfig(
          sportLabels.length ? sportLabels : ['No workouts'],
          sportLabels.length ? sportData : [1],
          sportLabels.length ? sportColors : [COLORS.muted]
        )
      );
    }

    function renderWorkouts(s) {
      const card = document.getElementById('workouts-card');
      const tbody = document.querySelector('#workouts-table tbody');
      const rows = s.recent_workouts || [];
      if (!rows.length) {
        card.style.display = 'none';
        return;
      }
      card.style.display = '';
      tbody.innerHTML = rows
        .map(
          (w) => `<tr>
            <td>${fmtDateTime(w.start)}</td>
            <td>${w.sport || '—'}</td>
            <td class="num">${fmt(w.strain, 1)}</td>
            <td class="num">${fmt(w.duration_minutes, 0)} min</td>
            <td class="num">${fmtInt(w.average_heart_rate)}</td>
            <td class="num">${fmtInt(w.max_heart_rate)}</td>
            <td class="num">${fmtInt(w.kilojoule)}</td>
          </tr>`
        )
        .join('');
    }

    function renderEmpty() {
      const main = document.querySelector('main');
      main.innerHTML = `<div class="empty">
        <p>No Whoop data in the selected window.</p>
        <p>Try a wider range, or run <code>POST /sync</code> first to pull your data.</p>
      </div>`;
    }

    async function load(days) {
      const meta = document.getElementById('meta');
      meta.innerHTML = '<span class="loading">Loading…</span>';
      try {
        const resp = await fetch(`/api/summary?days=${days}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const s = await resp.json();

        const name = s.profile && s.profile.name ? s.profile.name : 'You';
        const since = s.since ? new Date(s.since).toLocaleDateString() : '';
        meta.textContent = `${name} · last ${s.days} days · since ${since} · ${s.counts.cycles} days of data`;

        if (s.counts.cycles === 0 && s.counts.workouts === 0 && s.counts.sleeps === 0) {
          renderEmpty();
          return;
        }

        renderStats(s);
        renderCharts(s);
        renderWorkouts(s);
      } catch (err) {
        meta.innerHTML = `<span style="color: var(--red)">Failed to load: ${err.message}</span>`;
      }
    }

    document.getElementById('range').addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-days]');
      if (!btn) return;
      document
        .querySelectorAll('#range button')
        .forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      load(Number(btn.dataset.days));
    });

    load(30);
  </script>
</body>
</html>
"""
