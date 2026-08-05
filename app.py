"""
Lotto Scraper - local web app.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000 and click "Refresh Data".

Backend fetches/parses walottery.com's Top Prizes Remaining pages
(server-side, via `scraper.py`) and serves the result to a single-page
sortable/filterable table frontend.
"""

import json
import os
import threading

from flask import Flask, jsonify, Response

import scraper

app = Flask(__name__)

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "games.json")
_lock = threading.Lock()


def load_cached():
    if not os.path.exists(DATA_PATH):
        return {"scraped_at": None, "count": 0, "warnings": [], "games": []}
    with open(DATA_PATH) as f:
        return json.load(f)


@app.route("/api/games", methods=["GET"])
def get_games():
    return jsonify(load_cached())


@app.route("/api/refresh", methods=["POST"])
def refresh():
    with _lock:
        try:
            result = scraper.scrape_and_save(DATA_PATH)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify(result)


@app.route("/", methods=["GET"])
def index():
    return Response(INDEX_HTML, mimetype="text/html")


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Lotto Scraper</title>
<style>
  :root {
    --bg: #0f1115;
    --panel: #161923;
    --border: #2a2e3a;
    --text: #e7e9ee;
    --muted: #9aa1b1;
    --accent: #4f8cff;
    --good: #3ecf8e;
    --warn: #f0b429;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
  }
  header {
    padding: 20px 24px 12px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
  }
  h1 { font-size: 20px; margin: 0; }
  .sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
  .controls {
    display: flex; align-items: center; gap: 10px; padding: 14px 24px;
    flex-wrap: wrap;
  }
  input[type=text], select {
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 14px;
  }
  button {
    background: var(--accent);
    border: none;
    color: white;
    padding: 8px 14px;
    border-radius: 6px;
    font-size: 14px;
    cursor: pointer;
  }
  button:disabled { opacity: 0.6; cursor: default; }
  button.secondary {
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--text);
  }
  .banner {
    margin: 0 24px 12px;
    padding: 10px 14px;
    border-radius: 6px;
    background: rgba(240, 180, 41, 0.12);
    border: 1px solid var(--warn);
    color: var(--warn);
    font-size: 13px;
    display: none;
  }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  thead th {
    position: sticky; top: 0; background: var(--panel);
    text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border);
    cursor: pointer; user-select: none; white-space: nowrap;
    color: var(--muted); font-weight: 600;
  }
  thead th:hover { color: var(--text); }
  thead th.active { color: var(--accent); }
  tbody td { padding: 9px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  tbody tr.game-row:hover { background: rgba(255,255,255,0.03); cursor: pointer; }
  tbody tr.detail-row td { white-space: normal; background: rgba(255,255,255,0.02); }
  .name-cell { display: flex; align-items: center; gap: 8px; }
  .name-cell img { width: 28px; height: 28px; object-fit: cover; border-radius: 4px; }
  .pct-wrap { display: inline-flex; align-items: center; gap: 6px; }
  .pct-num { flex: 0 0 auto; }
  .pct-bar { flex: 0 0 60px; width: 60px; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .pct-bar-fill { display: block; height: 100%; background: var(--good); }
  .muted { color: var(--muted); }
  .wrap { padding: 0 24px 40px; overflow-x: auto; }
  .tier-table { width: auto; margin-top: 8px; font-size: 12px; }
  .tier-table th, .tier-table td { padding: 4px 10px; white-space: nowrap; }
  .spinner {
    display: inline-block; width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.4);
    border-top-color: white; border-radius: 50%; animation: spin 0.7s linear infinite; margin-right: 6px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  #emptyState { padding: 40px 24px; color: var(--muted); text-align: center; }
</style>
</head>
<body>

<header>
  <div>
    <h1>Lotto Scraper</h1>
    <div class="sub" id="lastUpdated">No data yet - click Refresh Data.</div>
  </div>
  <div>
    <button id="refreshBtn" onclick="refreshData()">Refresh Data</button>
  </div>
</header>

<div class="banner" id="warningBanner"></div>

<div class="controls">
  <input type="text" id="search" placeholder="Search game name..." oninput="render()">
  <select id="priceFilter" onchange="render()">
    <option value="">All prices</option>
    <option value="$1">$1</option>
    <option value="$2">$2</option>
    <option value="$3">$3</option>
    <option value="$5">$5</option>
    <option value="$10">$10</option>
    <option value="$20">$20</option>
    <option value="$30">$30</option>
  </select>
  <span class="muted" id="countLabel"></span>
</div>

<div class="wrap">
  <table id="gamesTable">
    <thead>
      <tr>
        <th data-key="name">Game</th>
        <th data-key="price">Price</th>
        <th data-key="game_number">Game #</th>
        <th data-key="top_prize_amount">Top Prize</th>
        <th data-key="top_prize_remaining">Top Prize Left</th>
        <th data-key="top_prize_pct_remaining">Top Prize % Left</th>
        <th data-key="total_prizes_remaining">All Prizes Left</th>
        <th data-key="total_prizes_pct_remaining">All Prizes % Left</th>
        <th data-key="remaining_cash_value">Remaining Cash Value</th>
        <th data-key="last_day_to_redeem">Last Day to Redeem</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
  <div id="emptyState" style="display:none;">No games loaded yet. Click "Refresh Data" above.</div>
</div>

<script>
let allGames = [];
let sortKey = "top_prize_pct_remaining";
let sortDir = -1; // -1 desc, 1 asc
let expandedId = null;

function money(n) {
  if (n === null || n === undefined) return "-";
  return "$" + Number(n).toLocaleString(undefined, {maximumFractionDigits: 0});
}
function num(n) {
  if (n === null || n === undefined) return "-";
  return Number(n).toLocaleString();
}
function pctBar(p) {
  if (p === null || p === undefined) return "-";
  const clamped = Math.max(0, Math.min(100, p));
  return `<span class="pct-wrap"><span class="pct-num">${p.toFixed(1)}%</span><span class="pct-bar"><span class="pct-bar-fill" style="width:${clamped}%"></span></span></span>`;
}

async function loadCached() {
  const res = await fetch("/api/games");
  const data = await res.json();
  applyData(data);
}

async function refreshData() {
  const btn = document.getElementById("refreshBtn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Refreshing...';
  try {
    const res = await fetch("/api/refresh", {method: "POST"});
    const data = await res.json();
    if (data.error) {
      alert("Refresh failed: " + data.error);
    } else {
      applyData(data);
    }
  } catch (e) {
    alert("Refresh failed: " + e);
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh Data";
  }
}

function applyData(data) {
  allGames = data.games || [];
  const banner = document.getElementById("warningBanner");
  if (data.warnings && data.warnings.length) {
    banner.style.display = "block";
    banner.textContent = "Warnings: " + data.warnings.join(" | ");
  } else {
    banner.style.display = "none";
  }
  const lu = document.getElementById("lastUpdated");
  lu.textContent = data.scraped_at ? ("Last updated: " + new Date(data.scraped_at).toLocaleString()) : "No data yet - click Refresh Data.";
  render();
}

function getFiltered() {
  const q = document.getElementById("search").value.trim().toLowerCase();
  const priceFilter = document.getElementById("priceFilter").value;
  let rows = allGames.filter(g => {
    if (priceFilter && g.price !== priceFilter) return false;
    if (q && !g.name.toLowerCase().includes(q)) return false;
    return true;
  });
  rows.sort((a, b) => {
    let av = a[sortKey], bv = b[sortKey];
    if (av === null || av === undefined) av = -Infinity;
    if (bv === null || bv === undefined) bv = -Infinity;
    if (typeof av === "string") { av = av.toLowerCase(); bv = (bv || "").toLowerCase(); }
    if (av < bv) return -1 * sortDir;
    if (av > bv) return 1 * sortDir;
    return 0;
  });
  return rows;
}

function render() {
  const rows = getFiltered();
  document.getElementById("countLabel").textContent = rows.length + " game(s)";
  document.getElementById("emptyState").style.display = allGames.length === 0 ? "block" : "none";

  document.querySelectorAll("thead th").forEach(th => {
    th.classList.toggle("active", th.dataset.key === sortKey);
  });

  const tbody = document.getElementById("tbody");
  tbody.innerHTML = "";
  for (const g of rows) {
    const tr = document.createElement("tr");
    tr.className = "game-row";
    tr.onclick = () => toggleExpand(g.id);
    tr.innerHTML = `
      <td><div class="name-cell"><img src="${g.image_url || ''}" onerror="this.style.display='none'"><span>${g.name}</span></div></td>
      <td>${g.price || '-'}</td>
      <td>${g.game_number || '-'}</td>
      <td>${money(g.top_prize_amount)}</td>
      <td>${num(g.top_prize_remaining)} / ${num(g.top_prize_total)}</td>
      <td>${pctBar(g.top_prize_pct_remaining)}</td>
      <td>${num(g.total_prizes_remaining)} / ${num(g.total_prizes_total)}</td>
      <td>${pctBar(g.total_prizes_pct_remaining)}</td>
      <td>${money(g.remaining_cash_value)}</td>
      <td>${g.last_day_to_redeem || '<span class="muted">Ongoing</span>'}</td>
    `;
    tbody.appendChild(tr);

    if (expandedId === g.id) {
      const detailTr = document.createElement("tr");
      detailTr.className = "detail-row";
      const td = document.createElement("td");
      td.colSpan = 10;
      td.innerHTML = buildTierTable(g);
      detailTr.appendChild(td);
      tbody.appendChild(detailTr);
    }
  }
}

function buildTierTable(g) {
  let html = `<table class="tier-table"><thead><tr>
    <th>Prize Amount</th><th>Total Prizes</th><th>Prizes Paid</th><th>Prizes Remaining</th>
  </tr></thead><tbody>`;
  for (const t of g.prize_tiers) {
    html += `<tr><td>${money(t.amount)}</td><td>${num(t.total)}</td><td>${num(t.paid)}</td><td>${num(t.remaining)}</td></tr>`;
  }
  html += `</tbody></table>`;
  return html;
}

function toggleExpand(id) {
  expandedId = expandedId === id ? null : id;
  render();
}

document.querySelectorAll("thead th").forEach(th => {
  th.addEventListener("click", () => {
    const key = th.dataset.key;
    if (sortKey === key) {
      sortDir *= -1;
    } else {
      sortKey = key;
      sortDir = -1;
    }
    render();
  });
});

loadCached();
</script>

</body>
</html>
"""


if __name__ == "__main__":
    app.run(debug=True, port=5000)
