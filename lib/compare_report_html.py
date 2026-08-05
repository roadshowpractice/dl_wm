"""Render a compare_transcripts() report (see transcript_compare.py) as a
self-contained, local HTML page: verdict banner, video identity cards,
a timeline-alignment scatter chart, verbatim run cards, and a filterable
fuzzy-match list. No external requests -- everything needed is inlined.

All sections that depend on optional data (word-level timestamps, video
metadata) degrade gracefully when that data isn't available for a given pair.
"""

from __future__ import annotations

import html
import json

from transcript_compare import format_hhmmss

_METADATA_FIELDS = [
    ("Uploader", "uploader", "str"),
    ("Uploaded", "video_date", "str"),
    ("Duration", "duration", "duration"),
    ("Resolution", "resolution", "str"),
    ("Views", "view_count", "int"),
    ("Likes", "like_count", "int"),
    ("Comments", "comment_count", "int"),
]

_STYLE = """
  :root {
    color-scheme: light;
    --bg:        #f3f4f0;
    --surface:   #ffffff;
    --surface-2: #ececE7;
    --ink:       #14171a;
    --ink-2:     #52514e;
    --ink-3:     #898781;
    --accent:    #2a78d6;
    --highlight: #eda100;
    --highlight-bg: rgba(237, 161, 0, 0.16);
    --border:    #e1e0d9;
    --border-strong: rgba(11,11,11,0.14);
    --good: #0ca30c;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --bg:        #0d0d0d;
      --surface:   #17191b;
      --surface-2: #1e2124;
      --ink:       #f2f2f0;
      --ink-2:     #c3c2b7;
      --ink-3:     #8d8b84;
      --accent:    #3987e5;
      --highlight: #c98500;
      --highlight-bg: rgba(201, 133, 0, 0.22);
      --border:    #2c2c2a;
      --border-strong: rgba(255,255,255,0.14);
      --good: #21c221;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --bg:        #0d0d0d;
    --surface:   #17191b;
    --surface-2: #1e2124;
    --ink:       #f2f2f0;
    --ink-2:     #c3c2b7;
    --ink-3:     #8d8b84;
    --accent:    #3987e5;
    --highlight: #c98500;
    --highlight-bg: rgba(201, 133, 0, 0.22);
    --border:    #2c2c2a;
    --border-strong: rgba(255,255,255,0.14);
    --good: #21c221;
  }
  :root[data-theme="light"] {
    color-scheme: light;
    --bg:        #f3f4f0;
    --surface:   #ffffff;
    --surface-2: #ececE7;
    --ink:       #14171a;
    --ink-2:     #52514e;
    --ink-3:     #898781;
    --accent:    #2a78d6;
    --highlight: #eda100;
    --highlight-bg: rgba(237, 161, 0, 0.16);
    --border:    #e1e0d9;
    --border-strong: rgba(11,11,11,0.14);
    --good: #0ca30c;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
    line-height: 1.5;
  }
  .page { max-width: 920px; margin: 0 auto; padding: 48px 24px 96px; }
  .mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
  h1, h2, h3 { font-family: ui-serif, Georgia, "Times New Roman", serif; text-wrap: balance; margin: 0; }
  .eyebrow {
    font-size: 0.72rem; letter-spacing: 0.09em; text-transform: uppercase;
    color: var(--ink-3); font-weight: 600;
  }
  header.doc-head { margin-bottom: 36px; }
  header.doc-head h1 { font-size: 2rem; margin: 6px 0 8px; }
  header.doc-head p { color: var(--ink-2); max-width: 62ch; margin: 0; }

  .verdict {
    display: grid; grid-template-columns: auto 1fr; gap: 20px; align-items: center;
    background: var(--surface); border: 1px solid var(--border); border-left: 4px solid var(--good);
    border-radius: 6px; padding: 22px 26px; margin-bottom: 40px;
  }
  .verdict .mark { font-size: 2rem; color: var(--good); line-height: 1; }
  .verdict h2 { font-size: 1.3rem; margin-bottom: 4px; }
  .verdict p { color: var(--ink-2); margin: 0; font-size: 0.95rem; }
  .verdict .stats { display: flex; gap: 28px; margin-top: 12px; flex-wrap: wrap; }
  .stat { display: flex; flex-direction: column; gap: 2px; }
  .stat .v { font-variant-numeric: tabular-nums; font-size: 1.25rem; font-weight: 600; }
  .stat .l { font-size: 0.72rem; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.06em; }

  section { margin-bottom: 48px; }
  section > h2 { font-size: 1.15rem; margin-bottom: 4px; }
  section > .sub { color: var(--ink-2); font-size: 0.9rem; margin: 0 0 18px; max-width: 68ch; }

  .cards { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  @media (max-width: 620px) { .cards { grid-template-columns: 1fr; } }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 18px 20px; }
  .card .stem { font-size: 0.78rem; color: var(--ink-3); }
  .card h3 { font-size: 1.02rem; margin: 2px 0 12px; }
  .card dl { margin: 0; display: grid; grid-template-columns: auto 1fr; gap: 6px 14px; font-size: 0.88rem; }
  .card dt { color: var(--ink-3); }
  .card dd { margin: 0; font-variant-numeric: tabular-nums; }

  .chart-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 20px 20px 12px; overflow-x: auto; }
  #timeline-canvas { display: block; }
  .chart-caption { font-size: 0.8rem; color: var(--ink-3); margin-top: 8px; }
  .tooltip {
    position: absolute; pointer-events: none; background: var(--ink); color: var(--bg);
    font-size: 0.78rem; padding: 8px 10px; border-radius: 4px; max-width: 280px;
    line-height: 1.4; opacity: 0; transition: opacity 0.08s ease; z-index: 5;
  }

  .run-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 14px 18px; margin-bottom: 10px; }
  .run-card .meta { display: flex; gap: 14px; font-size: 0.76rem; color: var(--ink-3); margin-bottom: 6px; }
  .run-card .meta .wc { color: var(--accent); font-weight: 600; }
  .run-card blockquote {
    margin: 0; font-size: 0.92rem; background: var(--highlight-bg);
    padding: 6px 10px; border-radius: 3px; border-left: 3px solid var(--highlight);
  }
  #runs-more {
    background: none; border: 1px solid var(--border-strong); color: var(--ink);
    border-radius: 4px; padding: 8px 14px; font-size: 0.85rem; cursor: pointer; margin-top: 4px;
  }
  #runs-more:hover { background: var(--surface-2); }

  .controls {
    display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 14px;
    background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 12px 16px;
  }
  .controls label { font-size: 0.78rem; color: var(--ink-2); display: flex; align-items: center; gap: 8px; }
  .controls input[type="text"] {
    font: inherit; padding: 5px 8px; border: 1px solid var(--border-strong); border-radius: 4px;
    background: var(--bg); color: var(--ink); min-width: 180px;
  }
  .controls input[type="range"] { accent-color: var(--accent); }
  .controls .count { margin-left: auto; font-size: 0.78rem; color: var(--ink-3); font-variant-numeric: tabular-nums; }
  .fuzzy-row {
    display: grid; grid-template-columns: 52px 1fr; gap: 12px; padding: 9px 4px;
    border-bottom: 1px solid var(--border); font-size: 0.86rem; align-items: start;
  }
  .fuzzy-row:last-child { border-bottom: none; }
  .fuzzy-row .ratio { font-variant-numeric: tabular-nums; color: var(--ink-2); padding-top: 2px; }
  .fuzzy-row .pair span { display: block; }
  .fuzzy-row .pair .a::before { content: "A  "; color: var(--ink-3); }
  .fuzzy-row .pair .b::before { content: "B  "; color: var(--ink-3); }
  .fuzzy-list-wrap {
    background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
    padding: 4px 16px; max-height: 480px; overflow-y: auto;
  }

  footer { color: var(--ink-3); font-size: 0.8rem; border-top: 1px solid var(--border); padding-top: 16px; margin-top: 56px; }
  a { color: var(--accent); }
"""

_SCRIPT = """
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function fmtTime(s) {
  s = Math.round(s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const mm = h ? String(m).padStart(2, "0") : m;
  const ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

const runsList = document.getElementById("runs-list");
const runsMoreBtn = document.getElementById("runs-more");
const INITIAL_RUNS = 12;

function renderRuns(count) {
  if (!runsList) return;
  runsList.innerHTML = runsData.slice(0, count).map(r => {
    const meta = hasTimestamps
      ? `<span class="mono">A ${fmtTime(r.a_start)} &rarr; B ${fmtTime(r.b_start)}</span><span class="mono">offset ${r.offset_seconds}s</span>`
      : `<span class="mono">word #${r.a_start_word} / #${r.b_start_word}</span>`;
    return `
    <div class="run-card">
      <div class="meta">
        <span class="wc">${r.word_count} words</span>
        ${meta}
      </div>
      <blockquote>&ldquo;${esc(r.text)}&rdquo;</blockquote>
    </div>
  `;
  }).join("");
}
if (runsList) {
  renderRuns(Math.min(INITIAL_RUNS, runsData.length));
  if (runsData.length <= INITIAL_RUNS && runsMoreBtn) {
    runsMoreBtn.style.display = "none";
  }
  if (runsMoreBtn) {
    runsMoreBtn.addEventListener("click", () => {
      renderRuns(runsData.length);
      runsMoreBtn.style.display = "none";
    });
  }
}

const fuzzyListEl = document.getElementById("fuzzy-list");
const ratioFilter = document.getElementById("ratio-filter");
const ratioValue = document.getElementById("ratio-value");
const textFilter = document.getElementById("text-filter");
const fuzzyCount = document.getElementById("fuzzy-count");

function renderFuzzy() {
  const minRatio = parseFloat(ratioFilter.value);
  const q = textFilter.value.trim().toLowerCase();
  const rows = fuzzyMatches.filter(m => {
    if (m.ratio < minRatio) return false;
    if (q && !(m.a_text.toLowerCase().includes(q) || m.b_text.toLowerCase().includes(q))) return false;
    return true;
  });
  fuzzyCount.textContent = rows.length;
  fuzzyListEl.innerHTML = rows.map(m => `
    <div class="fuzzy-row">
      <div class="ratio mono">${m.ratio.toFixed(2)}</div>
      <div class="pair">
        <span class="a">${esc(m.a_text)}</span>
        <span class="b">${esc(m.b_text)}</span>
      </div>
    </div>
  `).join("") || `<div style="padding:16px 4px;color:var(--ink-3);">No matches at this threshold.</div>`;
}
if (fuzzyListEl) {
  ratioFilter.addEventListener("input", () => {
    ratioValue.textContent = parseFloat(ratioFilter.value).toFixed(2);
    renderFuzzy();
  });
  textFilter.addEventListener("input", renderFuzzy);
  renderFuzzy();
}

const canvas = document.getElementById("timeline-canvas");
if (canvas && hasTimestamps && runsData.length) {
  const timedRuns = runsData;
  const ctx = canvas.getContext("2d");
  const tooltip = document.getElementById("tooltip");
  const DPR = window.devicePixelRatio || 1;
  const W = canvas.width, H = canvas.height;
  canvas.width = W * DPR;
  canvas.height = H * DPR;
  canvas.style.width = W + "px";
  canvas.style.height = H + "px";
  ctx.scale(DPR, DPR);

  const pad = { l: 46, r: 16, t: 12, b: 36 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;
  const maxT = Math.max(...timedRuns.map(r => Math.max(r.a_start, r.b_start))) * 1.04;

  function toPx(aStart, bStart) {
    return { x: pad.l + (aStart / maxT) * plotW, y: pad.t + plotH - (bStart / maxT) * plotH };
  }
  function getCSS(name) { return getComputedStyle(document.body).getPropertyValue(name).trim(); }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    const grid = getCSS("--border");
    const muted = getCSS("--ink-3");
    const accent = getCSS("--accent");
    const ink2 = getCSS("--ink-2");

    ctx.strokeStyle = grid;
    ctx.fillStyle = muted;
    ctx.font = "11px ui-monospace, Menlo, monospace";
    ctx.lineWidth = 1;
    for (let t = 0; t <= maxT; t += 120) {
      const { x } = toPx(t, 0);
      const { y } = toPx(0, t);
      ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + plotH); ctx.stroke();
      ctx.textAlign = "center"; ctx.fillText(fmtTime(t), x, pad.t + plotH + 16);
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(pad.l + plotW, y); ctx.stroke();
      ctx.textAlign = "right"; ctx.fillText(fmtTime(t), pad.l - 8, y + 4);
    }

    ctx.strokeStyle = getCSS("--border-strong") || grid;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t + plotH); ctx.lineTo(pad.l + plotW, pad.t + plotH);
    ctx.moveTo(pad.l, pad.t); ctx.lineTo(pad.l, pad.t + plotH);
    ctx.stroke();

    const med = offsetStats.median_offset_seconds || 0;
    ctx.save();
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = ink2;
    ctx.beginPath();
    const p1 = toPx(0, med);
    const p2 = toPx(maxT - med, maxT);
    ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y);
    ctx.stroke();
    ctx.restore();

    const maxWords = Math.max(...timedRuns.map(r => r.word_count));
    timedRuns.forEach(r => {
      const { x, y } = toPx(r.a_start, r.b_start);
      const radius = 3 + 6 * Math.sqrt(r.word_count / maxWords);
      ctx.beginPath();
      ctx.fillStyle = accent;
      ctx.globalAlpha = 0.82;
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = 1;
      ctx.strokeStyle = getCSS("--surface");
      ctx.stroke();
    });

    ctx.fillStyle = ink2;
    ctx.font = "12px -apple-system, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("Video A time \\u2192", pad.l, pad.t - 2);
    ctx.save();
    ctx.translate(12, pad.t + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.fillText("Video B time", 0, 0);
    ctx.restore();
  }
  draw();

  canvas.addEventListener("mousemove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    let hit = null, bestDist = 12;
    timedRuns.forEach(r => {
      const { x, y } = toPx(r.a_start, r.b_start);
      const d = Math.hypot(x - mx, y - my);
      if (d < bestDist) { bestDist = d; hit = r; }
    });
    if (hit) {
      tooltip.style.opacity = 1;
      const p = toPx(hit.a_start, hit.b_start);
      tooltip.style.left = (rect.left + window.scrollX + p.x + 14) + "px";
      tooltip.style.top = (rect.top + window.scrollY + p.y - 10) + "px";
      tooltip.innerHTML = `<strong>${hit.word_count} words</strong> &middot; A ${fmtTime(hit.a_start)} &rarr; B ${fmtTime(hit.b_start)} (offset ${hit.offset_seconds}s)<br>&ldquo;${esc(hit.text.slice(0, 90))}&hellip;&rdquo;`;
      canvas.style.cursor = "pointer";
    } else {
      tooltip.style.opacity = 0;
      canvas.style.cursor = "default";
    }
  });
  canvas.addEventListener("mouseleave", () => { tooltip.style.opacity = 0; });
}
"""


def _fmt_field(kind: str, value) -> str:
    if value is None:
        return "—"
    if kind == "duration" and isinstance(value, (int, float)):
        return format_hhmmss(value)
    if kind == "int" and isinstance(value, (int, float)):
        return f"{int(value):,}"
    return str(value)


def _identity_cards_html(meta_cmp: dict, stem_a: str, stem_b: str) -> str:
    def card(stem: str, side: str) -> str:
        title = meta_cmp.get("video_title", {}).get(side)
        rows = []
        for label, key, kind in _METADATA_FIELDS:
            entry = meta_cmp.get(key)
            if not entry:
                continue
            rows.append(
                f"<dt>{html.escape(label)}</dt>"
                f'<dd class="mono">{html.escape(_fmt_field(kind, entry.get(side)))}</dd>'
            )
        title_html = f"<h3>&ldquo;{html.escape(str(title))}&rdquo;</h3>" if title else ""
        return (
            f'<div class="card"><div class="stem mono">{side.upper()} &middot; '
            f'{html.escape(stem)}</div>{title_html}<dl>{"".join(rows)}</dl></div>'
        )

    return f'<div class="cards">{card(stem_a, "a")}{card(stem_b, "b")}</div>'


def _verdict_section(report: dict) -> str:
    verbatim_words = report["verbatim_word_total"]
    fuzzy_count = len(report["fuzzy_sentence_matches"])
    offset = report.get("time_offset_analysis")

    if not offset or not offset.get("count"):
        return (
            '<div class="verdict" style="border-left-color: var(--accent);">'
            '<div class="mark" style="color: var(--accent);">&#8776;</div><div>'
            "<h2>Verbatim &amp; fuzzy overlap</h2>"
            "<p>Word-level timestamps weren't available for both videos, "
            "so timeline analysis was skipped.</p>"
            '<div class="stats">'
            f'<div class="stat"><span class="v mono">{verbatim_words:,}</span>'
            '<span class="l">verbatim words shared</span></div>'
            f'<div class="stat"><span class="v mono">{fuzzy_count}</span>'
            '<span class="l">fuzzy sentence matches</span></div>'
            "</div></div></div>"
        )

    consistent = offset["consistent_timeline"]
    color = "var(--good)" if consistent else "var(--accent)"
    mark = "&#10003;" if consistent else "&#8776;"
    if consistent:
        headline = "Consistent single timeline &mdash; likely the same underlying recording"
        blurb = (
            f"{offset['count']} verbatim word-runs align to a near-constant time offset "
            f"between the two videos (stdev {offset['stdev_offset_seconds']}s). A fixed offset "
            "this tight usually means both are the same underlying recording, cut to start at "
            "slightly different points &mdash; not independently repeated material."
        )
    else:
        headline = "No consistent shared timeline &mdash; matches are scattered across time"
        blurb = (
            f"{offset['count']} verbatim word-runs were found, but their time offsets vary "
            f"widely (stdev {offset['stdev_offset_seconds']}s, range "
            f"[{offset['min_offset_seconds']}, {offset['max_offset_seconds']}]s). That's "
            "consistent with the shared material being delivered at unrelated points in time "
            "&mdash; i.e. reused/scripted language across separate occasions, rather than one "
            "recording."
        )

    return (
        f'<div class="verdict" style="border-left-color: {color};">'
        f'<div class="mark" style="color: {color};">{mark}</div><div>'
        f"<h2>{headline}</h2><p>{blurb}</p>"
        '<div class="stats">'
        f'<div class="stat"><span class="v mono">{offset["median_offset_seconds"]}s</span>'
        '<span class="l">median offset</span></div>'
        f'<div class="stat"><span class="v mono">&plusmn;{offset["stdev_offset_seconds"]}s</span>'
        '<span class="l">stdev</span></div>'
        f'<div class="stat"><span class="v mono">{verbatim_words:,}</span>'
        '<span class="l">verbatim words shared</span></div>'
        f'<div class="stat"><span class="v mono">{offset["count"]}</span>'
        '<span class="l">timed matches</span></div>'
        "</div></div></div>"
    )


def render_html_report(report: dict, stem_a: str, stem_b: str) -> str:
    """Render a compare_transcripts() report as a self-contained HTML page."""
    verbatim_runs = report["verbatim_runs"]
    fuzzy_matches = report["fuzzy_sentence_matches"]
    timed_runs = report.get("timed_verbatim_runs") or []
    offset_stats = report.get("time_offset_analysis") or {"count": 0}
    metadata_comparison = report.get("metadata_comparison")

    identity_section = ""
    if metadata_comparison:
        identity_section = f"""
  <section id="identity">
    <h2>Video identity</h2>
    <p class="sub">Pulled from each video's dl_wm metadata JSON.</p>
    {_identity_cards_html(metadata_comparison, stem_a, stem_b)}
  </section>"""

    timeline_section = ""
    if timed_runs:
        median = offset_stats.get("median_offset_seconds", 0)
        timeline_section = f"""
  <section id="timeline">
    <h2>Timeline alignment</h2>
    <p class="sub">Each point is one verbatim word-run: its position in video A (x) plotted against its position in video B (y). A tight diagonal means the same material lands at the same relative moment in both.</p>
    <div class="chart-wrap">
      <canvas id="timeline-canvas" width="860" height="420"></canvas>
      <div class="chart-caption">Hover a point for the matched passage. Dashed line: y = x + {median}s (median offset).</div>
    </div>
  </section>"""

    runs_section = ""
    if verbatim_runs:
        show_all_label = f"Show all {len(verbatim_runs)} runs"
        runs_section = f"""
  <section id="runs">
    <h2>Verbatim runs</h2>
    <p class="sub">Word-for-word identical stretches, longest first{' (timestamped where available)' if timed_runs else ''}.</p>
    <div id="runs-list"></div>
    <button id="runs-more" type="button">{html.escape(show_all_label)}</button>
  </section>"""
    else:
        runs_section = """
  <section id="runs">
    <h2>Verbatim runs</h2>
    <p class="sub">No verbatim word runs met the minimum length threshold.</p>
  </section>"""

    fuzzy_section = f"""
  <section id="fuzzy">
    <h2>Fuzzy sentence matches</h2>
    <p class="sub">Sentence pairs that are similar but not identical (paraphrase-level overlap), ranked by similarity. {len(fuzzy_matches)} total &mdash; filter below.</p>
    <div class="controls">
      <label>Min ratio
        <input type="range" id="ratio-filter" min="0" max="1" step="0.01" value="0">
        <span id="ratio-value" class="mono">0.00</span>
      </label>
      <label>Search
        <input type="text" id="text-filter" placeholder="filter by word or phrase&hellip;">
      </label>
      <span class="count"><span id="fuzzy-count">{len(fuzzy_matches)}</span> shown</span>
    </div>
    <div class="fuzzy-list-wrap" id="fuzzy-list"></div>
  </section>"""

    has_timestamps = bool(timed_runs)
    runs_data = timed_runs if has_timestamps else verbatim_runs

    data_js = (
        f"const runsData = {json.dumps(runs_data)};\n"
        f"const hasTimestamps = {json.dumps(has_timestamps)};\n"
        f"const fuzzyMatches = {json.dumps(fuzzy_matches)};\n"
        f"const offsetStats = {json.dumps(offset_stats)};\n"
    )

    return f"""<title>Comparison: {html.escape(stem_a)} vs {html.escape(stem_b)}</title>
<style>{_STYLE}</style>
<div class="page">
  <header class="doc-head">
    <div class="eyebrow">Transcript comparison &middot; dl_wm / call_compare_sources.py</div>
    <h1>{html.escape(stem_a)} <span class="mono" style="font-family:ui-serif, Georgia, serif; color:var(--ink-3); font-size:1.3rem;">vs</span> {html.escape(stem_b)}</h1>
    <p>Automatically generated comparison of these two video transcripts, checking for verbatim and near-duplicate language, and whether any shared material aligns to a single timeline.</p>
  </header>

  {_verdict_section(report)}
{identity_section}{timeline_section}{runs_section}{fuzzy_section}

  <footer>
    Generated by <span class="mono">bin/call_compare_sources.py</span> from each video's existing Whisper transcript and dl_wm metadata JSON. Verbatim runs via <span class="mono">difflib.SequenceMatcher</span> matching blocks; fuzzy matches via <span class="mono">difflib.get_close_matches</span> on sentence-split text.
  </footer>
</div>
<div class="tooltip" id="tooltip"></div>
<script>
{data_js}
{_SCRIPT}
</script>
"""
