#!/usr/bin/env python3
"""Generate a didactic, self-contained HTML dashboard for a HIL validation campaign.

Reads the structured facts (manifest.json, summary.csv, per-case metrics.json /
comparison.json) live from disk on every run, and merges them with a small
hand-maintained narrative file (campaign_story.json: level explanations, the
full experiment matrix definition, roadmap, findings) that does not change on
every simulation run. Output is a single static HTML file with relative links
to the real artifacts (overlay.html, metrics.json, README.md) already produced
by the verification pipeline -- nothing is re-plotted or copied.

Usage:
    python3 build_campaign_dashboard.py [--campaign DIR] [--story FILE] [-o OUT]

Defaults to the newest verification/results/*_campaign_*/ directory.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = REPO_ROOT / "verification" / "results"


# --------------------------------------------------------------------------
# Data loading helpers
# --------------------------------------------------------------------------

def find_latest_campaign() -> Path:
    candidates = sorted(p for p in RESULTS_ROOT.glob("*campaign*") if p.is_dir())
    if not candidates:
        raise SystemExit(f"Nenhuma campanha encontrada em {RESULTS_ROOT}")
    return candidates[-1]


def load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def read_summary_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            parsed = dict(row)
            for key in (
                "duration_s", "t_acc_s", "tload_nm", "csv_rows",
                "nrmse_i_alpha", "nrmse_i_beta", "mae_flux_alpha_wb",
                "mae_flux_beta_wb", "mae_speed_rad_s",
            ):
                val = row.get(key, "")
                try:
                    parsed[key] = float(val) if val not in ("", None) else None
                except ValueError:
                    parsed[key] = None
            rows.append(parsed)
    return rows


STATUS_RULES = [
    ("planned", "planejado", "status-muted"),
    ("next_planned", "planejado", "status-muted"),
]


def classify_status(status: str | None) -> tuple[str, str]:
    if not status:
        return "planejado", "status-muted"
    s = status.lower()
    if s in ("planned", "next_planned"):
        return "planejado", "status-muted"
    if "blocked" in s:
        if "generated" in s:
            return "parcial · bloqueado", "status-warning"
        return "bloqueado", "status-serious"
    if "generated" in s:
        return "executado", "status-good"
    return s.replace("_", " "), "status-muted"


def rel_href(dashboard_dir: Path, target: Path) -> str | None:
    if not target.is_file():
        return None
    try:
        import os
        return os.path.relpath(target, dashboard_dir)
    except ValueError:
        return None


def esc(value: Any) -> str:
    if value is None:
        return "—"
    return html.escape(str(value))


def fmt_pct(x: float | None, digits: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.{digits}f}%"


def fmt_sci(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:.3g}"


def fmt_num(x: float | None, digits: int = 3) -> str:
    if x is None:
        return "—"
    return f"{x:.{digits}g}"


METRIC_LABELS = [
    ("nrmse_i_alpha", "iα NRMSE", fmt_pct),
    ("nrmse_i_beta", "iβ NRMSE", fmt_pct),
    ("mae_flux_alpha_wb", "fluxα MAE [Wb]", fmt_sci),
    ("mae_flux_beta_wb", "fluxβ MAE [Wb]", fmt_sci),
    ("mae_speed_rad_s", "veloc. MAE [rad/s]", fmt_sci),
]


# --------------------------------------------------------------------------
# Resolving individual results (l2/l3 metrics.json, comparisons)
# --------------------------------------------------------------------------

def load_result(campaign_dir: Path, dashboard_dir: Path, relpath: str) -> dict[str, Any]:
    target_dir = campaign_dir / relpath
    metrics_doc = load_json(target_dir / "metrics.json")
    metrics = (metrics_doc or {}).get("metrics", {})
    return {
        "kind": "result",
        "relpath": relpath,
        "metrics_doc": metrics_doc,
        "metrics": metrics,
        "overlay_href": rel_href(dashboard_dir, target_dir / "overlay.html"),
        "readme_href": rel_href(dashboard_dir, target_dir / "README.md"),
        "metrics_href": rel_href(dashboard_dir, target_dir / "metrics.json"),
        "csv_href": next(
            (rel_href(dashboard_dir, p) for p in target_dir.glob("*.csv") if p.is_file()),
            None,
        ) if target_dir.is_dir() else None,
    }


def load_comparison(campaign_dir: Path, dashboard_dir: Path, relpath: str) -> dict[str, Any]:
    target_dir = campaign_dir / relpath
    doc = load_json(target_dir / "comparison.json")
    return {
        "kind": "comparison",
        "relpath": relpath,
        "doc": doc,
        "overlay_href": rel_href(dashboard_dir, target_dir / "overlay.html"),
        "readme_href": rel_href(dashboard_dir, target_dir / "README.md"),
        "comparison_href": rel_href(dashboard_dir, target_dir / "comparison.json"),
    }


# --------------------------------------------------------------------------
# HTML rendering
# --------------------------------------------------------------------------

def render_page(campaign_dir: Path, dashboard_dir: Path, manifest: dict, story: dict,
                 summary_rows: list[dict]) -> str:
    cases_by_id = {c["id"]: c for c in manifest.get("cases", [])}

    parts: list[str] = []
    parts.append(HEAD)
    parts.append(render_hero(manifest, story))
    parts.append(render_levels(story, cases_by_id))
    parts.append(render_stats(summary_rows, story))
    parts.append(render_chart(summary_rows))
    parts.append(render_matrix(story, cases_by_id))
    parts.append(render_roadmap(story))
    parts.append(render_findings(story))
    parts.append(render_cases_detail(campaign_dir, dashboard_dir, manifest))
    parts.append(FOOTER.format(commit=esc(manifest.get("git_commit", "—"))[:12],
                                created=esc(manifest.get("created_at", "—"))))
    parts.append(TAIL)
    return "\n".join(parts)


def render_hero(manifest: dict, story: dict) -> str:
    label = esc(story.get("campaign_label", manifest.get("campaign_id", "Campanha")))
    intro = esc(story.get("intro", ""))
    return f"""
<header class="hero">
  <p class="eyebrow">painel de validação &middot; hil / motor de indução em fpga</p>
  <h1>{label}</h1>
  <p class="hero-intro">{intro}</p>
</header>
"""


def render_levels(story: dict, cases_by_id: dict) -> str:
    # Count executed results per level across all cases (rough signal for the chain diagram)
    counts = {"L1": 0, "L2": 0, "L3": 0, "L4": 0}
    for case in cases_by_id.values():
        counts["L2"] += len(case.get("l2_results", {}))
        counts["L3"] += len(case.get("l3_results", {}))

    stages = []
    for lvl in story.get("levels", []):
        lid = lvl["id"]
        n = counts.get(lid, 0)
        active = "stage-active" if n > 0 else "stage-idle"
        count_txt = f"{n} ensaio{'s' if n != 1 else ''} registrado{'s' if n != 1 else ''}" if n > 0 else "sem ensaios ainda"
        stages.append(f"""
    <div class="stage {active}">
      <div class="stage-id">{esc(lid)}</div>
      <div class="stage-title">{esc(lvl['title'])}</div>
      <p class="stage-question">{esc(lvl['question'])}</p>
      <p class="stage-note">{esc(lvl['note'])}</p>
      <div class="stage-count">{esc(count_txt)}</div>
    </div>""")
    chain = '<div class="connector" aria-hidden="true">&#10230;</div>'.join(stages)
    return f"""
<section class="section" id="niveis">
  <h2><span class="section-index">01</span> A cadeia de validação (L1&rarr;L4)</h2>
  <p class="section-lede">Cada nível responde uma pergunta específica e introduz uma nova fonte de erro possível. Se um erro aparece em L4 mas não em L2, ele provávelmente vem da integração em hardware &mdash; não do modelo.</p>
  <div class="chain">{chain}</div>
</section>
"""


def render_stats(summary_rows: list[dict], story: dict) -> str:
    executed = sum(1 for r in summary_rows if r.get("status") == "generated")
    blocked = sum(1 for r in summary_rows if "blocked" in (r.get("status") or ""))
    planned = sum(1 for r in summary_rows if (r.get("status") or "") in ("planned", "next_planned"))
    total_matrix_cases = sum(len(g["cases"]) for g in story.get("matrix", {}).values())
    tiles = [
        (str(executed), "resultados executados"),
        (str(blocked), "bloqueados / pendentes"),
        (str(planned), "planejados na fila"),
        (str(total_matrix_cases), "casos definidos na matriz"),
    ]
    tiles_html = "".join(
        f'<div class="tile"><div class="tile-value">{esc(v)}</div><div class="tile-label">{esc(l)}</div></div>'
        for v, l in tiles
    )
    return f"""
<section class="section" id="status">
  <h2><span class="section-index">02</span> Status atual da campanha</h2>
  <div class="tiles">{tiles_html}</div>
</section>
"""


def render_chart(summary_rows: list[dict]) -> str:
    rows = [r for r in summary_rows if r.get("nrmse_i_alpha") is not None]
    if not rows:
        return ""
    max_val = max(max(r["nrmse_i_alpha"], r["nrmse_i_beta"]) for r in rows)
    scale_max = max_val * 1.15
    row_h = 46
    chart_w = 640
    label_w = 190
    plot_w = chart_w - label_w - 60
    svg_rows = []
    y = 10
    for r in rows:
        label = f"{r['case']} · {r['level']}"
        a_val = r["nrmse_i_alpha"]
        b_val = r["nrmse_i_beta"]
        a_w = (a_val / scale_max) * plot_w
        b_w = (b_val / scale_max) * plot_w
        svg_rows.append(f"""
    <g class="bar-row" transform="translate(0,{y})">
      <text x="{label_w - 10}" y="12" text-anchor="end" class="bar-label">{esc(label)}</text>
      <rect x="{label_w}" y="0" width="{a_w:.1f}" height="12" rx="3" class="bar bar-alpha"
            data-tip="{esc(label)} — iα NRMSE {fmt_pct(a_val)}"/>
      <rect x="{label_w}" y="16" width="{b_w:.1f}" height="12" rx="3" class="bar bar-beta"
            data-tip="{esc(label)} — iβ NRMSE {fmt_pct(b_val)}"/>
    </g>""")
        y += row_h
    total_h = y + 30
    # simple gridlines at 0 / mid / max
    ticks = [0, scale_max / 2, scale_max]
    grid = "".join(
        f'<line x1="{label_w + (t / scale_max) * plot_w:.1f}" y1="0" x2="{label_w + (t / scale_max) * plot_w:.1f}" '
        f'y2="{y - row_h + 30:.1f}" class="grid-line"/>'
        f'<text x="{label_w + (t / scale_max) * plot_w:.1f}" y="{y - row_h + 44:.1f}" '
        f'text-anchor="middle" class="grid-label">{fmt_pct(t, 0)}</text>'
        for t in ticks
    )
    svg = f"""
<svg viewBox="0 0 {chart_w} {total_h}" class="chart-svg" role="img"
     aria-label="NRMSE de corrente por ensaio">
  {grid}
  {''.join(svg_rows)}
</svg>"""
    return f"""
<section class="section" id="grafico">
  <h2><span class="section-index">03</span> Erro de corrente por ensaio</h2>
  <p class="section-lede">NRMSE de i&alpha; e i&beta; contra a referência C/C++, para cada resultado principal já executado. Passe o mouse sobre uma barra para ver o valor exato. Quanto menor, mais próxima a FPGA/VHDL fica da referência offline.</p>
  <div class="legend">
    <span class="legend-item"><span class="swatch swatch-alpha"></span> i&alpha; NRMSE</span>
    <span class="legend-item"><span class="swatch swatch-beta"></span> i&beta; NRMSE</span>
  </div>
  <div class="chart-wrap">{svg}</div>
  <div id="tooltip" class="tooltip" hidden></div>
</section>
"""


def render_matrix(story: dict, cases_by_id: dict) -> str:
    blocks = []
    for gid, group in story.get("matrix", {}).items():
        rows = []
        for c in group["cases"]:
            cid = c["id"]
            manifest_case = cases_by_id.get(cid)
            if manifest_case:
                label, css = classify_status(manifest_case.get("status"))
                anchor = f'<a href="#case-{esc(cid)}" class="case-link">{esc(cid)}</a>'
            else:
                label, css = "planejado", "status-muted"
                anchor = f'<span class="case-id-static">{esc(cid)}</span>'
            extra_cols = ""
            if "rampa" in c:
                extra_cols = f"<td>{esc(c['rampa'])}</td><td>{esc(c['carga'])}</td>"
            elif "condicao" in c:
                extra_cols = f"<td>{esc(c['condicao'])}</td><td>{esc(c['perturbacao'])}</td>"
            elif "acao" in c:
                extra_cols = f"<td>{esc(c['acao'])}</td><td>{esc(c['carga'])}</td>"
            rows.append(f"""
        <tr>
          <td class="mono">{anchor}</td>
          {extra_cols}
          <td>{esc(c['objetivo'])}</td>
          <td><span class="badge {css}">{esc(label)}</span></td>
        </tr>""")
        if group["cases"] and "rampa" in group["cases"][0]:
            col_headers = "<th>ID</th><th>Rampa</th><th>Carga</th><th>Objetivo</th><th>Status</th>"
        elif group["cases"] and "condicao" in group["cases"][0]:
            col_headers = "<th>ID</th><th>Condição inicial</th><th>Perturbação</th><th>Objetivo</th><th>Status</th>"
        else:
            col_headers = "<th>ID</th><th>Ação</th><th>Carga</th><th>Objetivo</th><th>Status</th>"
        blocks.append(f"""
    <div class="matrix-group">
      <h3>Grupo {esc(gid)} &middot; {esc(group['label'])}</h3>
      <p class="group-desc">{esc(group.get('description', ''))}</p>
      <table class="matrix-table">
        <thead><tr>{col_headers}</tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>""")
    return f"""
<section class="section" id="matriz">
  <h2><span class="section-index">04</span> Matriz de experimentos</h2>
  <p class="section-lede">Define todo o espaço de ensaios planejado para a dissertação. IDs em destaque já têm dado gerado nesta campanha e levam direto ao ensaio na seção 07.</p>
  {''.join(blocks)}
</section>
"""


def render_roadmap(story: dict) -> str:
    items = "".join(f"<li><span class='step-no'>{i+1:02d}</span><span>{esc(step)}</span></li>"
                     for i, step in enumerate(story.get("roadmap", [])))
    return f"""
<section class="section" id="roteiro">
  <h2><span class="section-index">05</span> Fila de execução / próximos passos</h2>
  <ol class="roadmap">{items}</ol>
</section>
"""


def render_findings(story: dict) -> str:
    entries = []
    for f in story.get("findings", []):
        entries.append(f"""
    <li class="finding">
      <div class="finding-date mono">{esc(f.get('date', ''))}</div>
      <div class="finding-body">
        <h4>{esc(f['title'])}</h4>
        <p>{esc(f['text'])}</p>
      </div>
    </li>""")
    return f"""
<section class="section" id="achados">
  <h2><span class="section-index">06</span> Diário de investigação &mdash; achados metodológicos</h2>
  <p class="section-lede">Cada item eliminou uma hipótese sobre a origem do erro observado na partida, na ordem em que foi investigado.</p>
  <ul class="findings">{''.join(entries)}</ul>
</section>
"""


def render_stimulus(metrics_doc: dict | None) -> str:
    if not metrics_doc:
        return ""
    vf = metrics_doc.get("vf", {})
    motor = metrics_doc.get("motor", {})
    bits = []
    if vf:
        bits.append(f"f={fmt_num(vf.get('f_nominal_hz'))} Hz")
        bits.append(f"V_pico={fmt_num(vf.get('v_peak_nominal_v'))} V")
        bits.append(f"t_acc={fmt_num(vf.get('t_acc_s'))} s")
        bits.append(f"Tload={fmt_num(vf.get('tload_nm'))} Nm")
    if motor:
        bits.append(f"Rs={fmt_num(motor.get('rs'))}")
        bits.append(f"J={fmt_num(motor.get('j'))}")
        bits.append(f"Ts={fmt_num(motor.get('ts'))} s")
    if metrics_doc.get("csv_rows"):
        bits.append(f"{metrics_doc['csv_rows']} linhas CSV")
    if not bits:
        return ""
    return f'<p class="stimulus mono">{esc(" · ".join(bits))}</p>'


def render_actions(overlay_href, readme_href, metrics_href, csv_href=None) -> str:
    buttons = []
    for href, txt in (
        (overlay_href, "Abrir overlay.html"),
        (metrics_href, "Ver metrics.json"),
        (readme_href, "Ler README.md"),
        (csv_href, "Baixar CSV"),
    ):
        if href:
            buttons.append(f'<a class="btn" href="{esc(href)}" target="_blank" rel="noopener">{txt}</a>')
    if not buttons:
        return '<p class="no-artifact">Nenhum artefato gerado ainda para este ensaio.</p>'
    return f'<div class="actions">{"".join(buttons)}</div>'


def render_result_card(key: str, info: dict) -> str:
    metrics = info.get("metrics") or {}
    metrics_doc = info.get("metrics_doc")
    headline = "".join(
        f'<span class="metric-chip"><span class="metric-k">{lbl}</span>'
        f'<span class="metric-v">{fmt(metrics.get(k))}</span></span>'
        for k, lbl, fmt in METRIC_LABELS if metrics.get(k) is not None
    )
    level = esc((metrics_doc or {}).get("level", ""))
    table_rows = "".join(
        f"<tr><td>{lbl}</td><td class='mono num'>{fmt(metrics.get(k))}</td></tr>"
        for k, lbl, fmt in METRIC_LABELS if metrics.get(k) is not None
    )
    return f"""
      <details class="card">
        <summary>
          <span class="card-key mono">{esc(key)}</span>
          <span class="card-level badge status-muted">{level or 'L2/L3'}</span>
          <span class="card-headline">{headline or 'sem métricas registradas'}</span>
        </summary>
        <div class="card-body">
          {render_stimulus(metrics_doc)}
          <table class="metrics-table"><tbody>{table_rows}</tbody></table>
          {render_actions(info.get('overlay_href'), info.get('readme_href'), info.get('metrics_href'), info.get('csv_href'))}
          <p class="path mono">{esc(info['relpath'])}</p>
        </div>
      </details>"""


def render_comparison_card(key: str, info: dict) -> str:
    doc = info.get("doc") or {}
    l2m = doc.get("l2", {}).get("metrics", {})
    l3m = doc.get("l3", {}).get("metrics", {})
    rows = "".join(
        f"<tr><td>{lbl}</td><td class='mono num'>{fmt(l2m.get(k))}</td><td class='mono num'>{fmt(l3m.get(k))}</td></tr>"
        for k, lbl, fmt in METRIC_LABELS if l2m.get(k) is not None or l3m.get(k) is not None
    )
    interp = "".join(f"<li>{esc(s)}</li>" for s in doc.get("interpretation", []))
    interp_html = f'<ul class="interpretation">{interp}</ul>' if interp else ""
    headline = ""
    if l2m.get("nrmse_i_alpha") is not None:
        headline = f"L2 iα {fmt_pct(l2m.get('nrmse_i_alpha'))} vs L3 iα {fmt_pct(l3m.get('nrmse_i_alpha'))}"
    return f"""
      <details class="card">
        <summary>
          <span class="card-key mono">{esc(key)}</span>
          <span class="card-level badge status-muted">comparativo</span>
          <span class="card-headline">{esc(headline) or 'ver detalhes'}</span>
        </summary>
        <div class="card-body">
          <table class="metrics-table">
            <thead><tr><th></th><th>L2</th><th>L3</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
          {interp_html}
          {render_actions(info.get('overlay_href'), info.get('readme_href'), info.get('comparison_href'))}
          <p class="path mono">{esc(info['relpath'])}</p>
        </div>
      </details>"""


def render_cases_detail(campaign_dir: Path, dashboard_dir: Path, manifest: dict) -> str:
    blocks = []
    for case in manifest.get("cases", []):
        cid = case["id"]
        label, css = classify_status(case.get("status"))
        meta_bits = []
        if "freq_hz" in case:
            meta_bits.append(f"f={case['freq_hz']} Hz")
        if "t_acc_s" in case:
            meta_bits.append(f"t_acc={case['t_acc_s']} s")
        if "load_tn" in case:
            meta_bits.append(f"carga={case['load_tn']} Tn")
        if "load_tn_initial" in case:
            meta_bits.append(f"carga={case['load_tn_initial']}→{case.get('load_tn_final')} Tn")
        if case.get("tload_nm") is not None:
            meta_bits.append(f"Tload={fmt_num(case['tload_nm'])} Nm")

        sections = []
        l2_results = case.get("l2_results", {})
        if l2_results:
            cards = "".join(render_result_card(k, load_result(campaign_dir, dashboard_dir, v))
                             for k, v in l2_results.items())
            sections.append(f'<div class="result-group"><h4>Nível L2 ({len(l2_results)})</h4><div class="card-grid">{cards}</div></div>')
        l3_results = case.get("l3_results", {})
        if l3_results:
            cards = "".join(render_result_card(k, load_result(campaign_dir, dashboard_dir, v))
                             for k, v in l3_results.items())
            sections.append(f'<div class="result-group"><h4>Nível L3 ({len(l3_results)})</h4><div class="card-grid">{cards}</div></div>')
        comparisons = case.get("comparisons", {})
        if comparisons:
            cards = "".join(render_comparison_card(k, load_comparison(campaign_dir, dashboard_dir, v))
                             for k, v in comparisons.items())
            sections.append(f'<div class="result-group"><h4>Comparativos ({len(comparisons)})</h4><div class="card-grid">{cards}</div></div>')

        blocker = ""
        if case.get("l3_blocker"):
            blocker = f'<p class="blocker">Bloqueado: {esc(case["l3_blocker"])} &middot; script: <code>{esc(case.get("l3_run_script", ""))}</code></p>'
        elif case.get("l2_run_script"):
            blocker = f'<p class="blocker">Pronto para rodar: <code>{esc(case["l2_run_script"])}</code></p>'

        summary_html = f'<p class="case-summary">{esc(case["summary"])}</p>' if case.get("summary") else ""
        if not sections and not blocker and not summary_html:
            sections.append('<p class="no-artifact">Caso planejado; sem dados gerados nesta campanha ainda.</p>')

        blocks.append(f"""
    <article class="case-block" id="case-{esc(cid)}">
      <div class="case-block-header">
        <h3><span class="mono">{esc(cid)}</span> <span class="case-dir mono">{esc(case.get('dir', ''))}</span></h3>
        <span class="badge {css}">{esc(label)}</span>
      </div>
      <p class="case-meta mono">{esc(' · '.join(meta_bits))}</p>
      {summary_html}
      {blocker}
      {''.join(sections)}
    </article>""")
    return f"""
<section class="section" id="ensaios">
  <h2><span class="section-index">07</span> Ensaios detalhados por caso</h2>
  <p class="section-lede">Clique em qualquer ensaio para expandir parâmetros e métricas, e abrir o gráfico interativo real gerado pelo pipeline.</p>
  {''.join(blocks)}
</section>
"""


# --------------------------------------------------------------------------
# Static HEAD / CSS / FOOTER / TAIL
# --------------------------------------------------------------------------

HEAD = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel de Validação HIL</title>
<style>
:root {
  --page: #f9f9f7;
  --panel: #fcfcfb;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --hairline: #e1e0d9;
  --baseline: #c3c2b7;
  --accent: #b8790a;
  --accent-ink: #6e4802;
  --series-alpha: #2a78d6;
  --series-beta: #1baf7a;
  --status-good-bg: #e4f6e0;
  --status-good-fg: #0d6b0d;
  --status-warning-bg: #fdf0d8;
  --status-warning-fg: #8a5c05;
  --status-serious-bg: #fbe4da;
  --status-serious-fg: #99381a;
  --status-muted-bg: #ececea;
  --status-muted-fg: #6b6a66;
  --font-mono: ui-monospace, "SFMono-Regular", "JetBrains Mono", Consolas, "Liberation Mono", monospace;
  --font-sans: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --page: #0d0d0d;
    --panel: #1a1a19;
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --muted: #a19f98;
    --hairline: #2c2c2a;
    --baseline: #383835;
    --accent: #d99a2b;
    --accent-ink: #f0b957;
    --series-alpha: #3987e5;
    --series-beta: #199e70;
    --status-good-bg: #123317;
    --status-good-fg: #6fdc7f;
    --status-warning-bg: #3a2c0c;
    --status-warning-fg: #fab219;
    --status-serious-bg: #3a1c14;
    --status-serious-fg: #ec835a;
    --status-muted-bg: #232322;
    --status-muted-fg: #a19f98;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--page);
  color: var(--ink);
  font-family: var(--font-sans);
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent-ink); }
.mono { font-family: var(--font-mono); }
.num { text-align: right; font-variant-numeric: tabular-nums; }

.hero {
  padding: 4rem 1.5rem 3rem;
  max-width: 980px;
  margin: 0 auto;
  background-image:
    linear-gradient(var(--hairline) 1px, transparent 1px),
    linear-gradient(90deg, var(--hairline) 1px, transparent 1px);
  background-size: 28px 28px;
  background-position: center top;
  -webkit-mask-image: linear-gradient(to bottom, black 60%, transparent 100%);
          mask-image: linear-gradient(to bottom, black 60%, transparent 100%);
}
.eyebrow {
  font-family: var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.72rem;
  color: var(--accent-ink);
  margin: 0 0 0.9rem;
}
.hero h1 { font-size: clamp(1.9rem, 4vw, 2.7rem); margin: 0 0 1rem; letter-spacing: -0.01em; }
.hero-intro { max-width: 62ch; color: var(--ink-2); font-size: 1.05rem; }

.section { max-width: 980px; margin: 0 auto; padding: 2.6rem 1.5rem; border-top: 1px solid var(--hairline); }
.section h2 { font-size: 1.4rem; display: flex; align-items: baseline; gap: 0.6rem; margin: 0 0 0.6rem; }
.section-index {
  font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-ink);
  border: 1px solid var(--hairline); border-radius: 4px; padding: 0.05rem 0.4rem;
}
.section-lede { color: var(--ink-2); max-width: 68ch; margin: 0 0 1.4rem; }

/* L1-L4 chain */
.chain { display: flex; align-items: stretch; gap: 0; overflow-x: auto; padding-bottom: 0.5rem; }
.stage {
  flex: 1 1 200px; min-width: 200px; background: var(--panel);
  border: 1px solid var(--hairline); border-radius: 10px; padding: 1rem 1.1rem;
  position: relative;
}
.stage-idle { opacity: 0.6; }
.stage-active { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; }
.stage-id { font-family: var(--font-mono); font-size: 1.4rem; color: var(--accent-ink); font-weight: 600; }
.stage-title { font-weight: 600; margin: 0.15rem 0 0.5rem; }
.stage-question { font-size: 0.85rem; color: var(--ink-2); margin: 0 0 0.5rem; }
.stage-note { font-size: 0.78rem; color: var(--muted); margin: 0 0 0.6rem; }
.stage-count { font-family: var(--font-mono); font-size: 0.72rem; color: var(--accent-ink); }
.connector {
  display: flex; align-items: center; justify-content: center; width: 2.2rem;
  color: var(--baseline); font-size: 1.2rem; flex: 0 0 auto;
}

/* stat tiles */
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px; background: var(--hairline); border: 1px solid var(--hairline); border-radius: 10px; overflow: hidden; }
.tile { background: var(--panel); padding: 1.1rem 1rem; }
.tile-value { font-family: var(--font-mono); font-size: 2rem; font-variant-numeric: tabular-nums; color: var(--accent-ink); }
.tile-label { font-size: 0.8rem; color: var(--ink-2); margin-top: 0.2rem; }

/* chart */
.legend { display: flex; gap: 1.2rem; font-size: 0.85rem; color: var(--ink-2); margin-bottom: 0.8rem; }
.legend-item { display: flex; align-items: center; gap: 0.4rem; }
.swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.swatch-alpha { background: var(--series-alpha); }
.swatch-beta { background: var(--series-beta); }
.chart-wrap { background: var(--panel); border: 1px solid var(--hairline); border-radius: 10px; padding: 1rem; overflow-x: auto; }
.chart-svg { width: 100%; height: auto; min-width: 560px; }
.bar-label { font-family: var(--font-mono); font-size: 9px; fill: var(--ink-2); }
.bar { fill: var(--series-alpha); cursor: pointer; }
.bar-beta { fill: var(--series-beta); }
.grid-line { stroke: var(--hairline); stroke-width: 1; }
.grid-label { font-family: var(--font-mono); font-size: 9px; fill: var(--muted); }
.tooltip {
  position: fixed; background: var(--ink); color: var(--page); font-family: var(--font-mono);
  font-size: 0.75rem; padding: 0.35rem 0.6rem; border-radius: 6px; pointer-events: none;
  z-index: 50; max-width: 320px;
}

/* matrix */
.matrix-group { margin-bottom: 1.8rem; }
.matrix-group h3 { font-size: 1.05rem; margin-bottom: 0.2rem; }
.group-desc { color: var(--ink-2); font-size: 0.88rem; margin: 0 0 0.7rem; }
.matrix-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
.matrix-table th { text-align: left; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); border-bottom: 1px solid var(--hairline); padding: 0.4rem 0.6rem; }
.matrix-table td { padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--hairline); }
.case-link { font-weight: 600; }
.case-id-static { color: var(--muted); }

.badge {
  display: inline-block; font-size: 0.72rem; font-family: var(--font-mono); padding: 0.15rem 0.5rem;
  border-radius: 999px; white-space: nowrap;
}
.status-good { background: var(--status-good-bg); color: var(--status-good-fg); }
.status-warning { background: var(--status-warning-bg); color: var(--status-warning-fg); }
.status-serious { background: var(--status-serious-bg); color: var(--status-serious-fg); }
.status-muted { background: var(--status-muted-bg); color: var(--status-muted-fg); }

/* roadmap */
.roadmap { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.6rem; }
.roadmap li { display: flex; gap: 0.9rem; align-items: baseline; padding: 0.6rem 0.8rem; background: var(--panel); border: 1px solid var(--hairline); border-radius: 8px; }
.step-no { font-family: var(--font-mono); color: var(--accent-ink); font-weight: 600; }

/* findings */
.findings { list-style: none; margin: 0; padding: 0; border-left: 2px solid var(--hairline); }
.finding { display: flex; gap: 1.2rem; padding: 0 0 1.4rem 1.2rem; margin-left: -2px; border-left: 2px solid var(--accent); }
.finding:last-child { padding-bottom: 0; }
.finding-date { flex: 0 0 auto; font-size: 0.75rem; color: var(--muted); padding-top: 0.15rem; }
.finding-body h4 { margin: 0 0 0.3rem; font-size: 1rem; }
.finding-body p { margin: 0; color: var(--ink-2); font-size: 0.92rem; max-width: 68ch; }

/* case detail */
.case-block { border: 1px solid var(--hairline); border-radius: 10px; padding: 1.2rem 1.3rem; margin-bottom: 1.4rem; background: var(--panel); }
.case-block-header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.case-block-header h3 { margin: 0; font-size: 1.1rem; display: flex; gap: 0.6rem; align-items: baseline; }
.case-dir { font-size: 0.78rem; color: var(--muted); font-weight: 400; }
.case-meta { font-size: 0.78rem; color: var(--ink-2); margin: 0.3rem 0 0.6rem; }
.case-summary { font-size: 0.92rem; color: var(--ink-2); margin: 0.2rem 0 0.6rem; }
.blocker { font-size: 0.85rem; color: var(--status-warning-fg); background: var(--status-warning-bg); border-radius: 6px; padding: 0.4rem 0.6rem; margin: 0.4rem 0; }
.result-group { margin-top: 1rem; }
.result-group h4 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); margin: 0 0 0.5rem; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 0.7rem; }

.card { background: var(--page); border: 1px solid var(--hairline); border-radius: 8px; }
.card summary {
  cursor: pointer; padding: 0.7rem 0.85rem; display: flex; gap: 0.5rem; align-items: center;
  flex-wrap: wrap; list-style: none;
}
.card summary::-webkit-details-marker { display: none; }
.card summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.card-key { font-size: 0.82rem; font-weight: 600; }
.card-level { font-size: 0.65rem; }
.card-headline { font-size: 0.78rem; color: var(--ink-2); flex: 1 1 auto; }
.metric-chip { display: inline-flex; gap: 0.25rem; margin-right: 0.6rem; font-size: 0.78rem; }
.metric-k { color: var(--muted); }
.metric-v { font-family: var(--font-mono); color: var(--accent-ink); }
.card-body { padding: 0 0.85rem 0.85rem; border-top: 1px solid var(--hairline); }
.stimulus { font-size: 0.78rem; color: var(--ink-2); margin: 0.6rem 0; }
.metrics-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin: 0.5rem 0; }
.metrics-table th, .metrics-table td { padding: 0.25rem 0.4rem; border-bottom: 1px solid var(--hairline); text-align: left; }
.interpretation { font-size: 0.85rem; color: var(--ink-2); padding-left: 1.1rem; }
.actions { display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.6rem 0; }
.btn {
  font-size: 0.78rem; font-family: var(--font-mono); text-decoration: none; color: var(--ink);
  background: var(--panel); border: 1px solid var(--hairline); border-radius: 6px; padding: 0.35rem 0.6rem;
}
.btn:hover { border-color: var(--accent); color: var(--accent-ink); }
.no-artifact { font-size: 0.82rem; color: var(--muted); font-style: italic; }
.path { font-size: 0.7rem; color: var(--muted); margin-top: 0.4rem; }

footer { max-width: 980px; margin: 0 auto; padding: 2rem 1.5rem 4rem; color: var(--muted); font-size: 0.78rem; border-top: 1px solid var(--hairline); }

@media (max-width: 640px) {
  .chain { flex-direction: column; }
  .connector { transform: rotate(90deg); }
}
</style>
</head>
<body>
"""

FOOTER = """
<footer>
  Gerado automaticamente por <code class="mono">verification/cocotb/scripts/build_campaign_dashboard.py</code>
  a partir de <code class="mono">manifest.json</code>, <code class="mono">summary.csv</code> e os
  <code class="mono">metrics.json</code>/<code class="mono">comparison.json</code> de cada ensaio.
  Commit da campanha: <span class="mono">{commit}</span> &middot; manifesto criado em <span class="mono">{created}</span>.
  Metodologia completa em <code class="mono">docs/experimental-validation-plan.md</code>.
</footer>
"""

TAIL = """
<script>
(function () {
  const tooltip = document.getElementById('tooltip');
  if (!tooltip) return;
  document.querySelectorAll('.bar').forEach(function (bar) {
    bar.addEventListener('mousemove', function (ev) {
      tooltip.textContent = bar.getAttribute('data-tip');
      tooltip.style.left = (ev.clientX + 14) + 'px';
      tooltip.style.top = (ev.clientY + 14) + 'px';
      tooltip.hidden = false;
    });
    bar.addEventListener('mouseleave', function () { tooltip.hidden = true; });
  });
})();
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", type=Path, default=None, help="Diretório da campanha (default: mais recente em verification/results/)")
    ap.add_argument("--story", type=Path, default=None, help="Arquivo campaign_story.json (default: <campanha>/campaign_story.json)")
    ap.add_argument("-o", "--output", type=Path, default=None, help="Arquivo HTML de saída (default: <campanha>/index.html, para abrir servindo a raiz da campanha)")
    args = ap.parse_args()

    campaign_dir = args.campaign or find_latest_campaign()
    campaign_dir = campaign_dir.resolve()
    story_path = args.story or (campaign_dir / "campaign_story.json")
    output_path = args.output or (campaign_dir / "index.html")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = load_json(campaign_dir / "manifest.json")
    if manifest is None:
        raise SystemExit(f"manifest.json não encontrado em {campaign_dir}")
    story = load_json(story_path)
    if story is None:
        raise SystemExit(f"campaign_story.json não encontrado em {story_path}")
    summary_rows = read_summary_csv(campaign_dir / "campaign_dashboard" / "summary.csv")

    html_out = render_page(campaign_dir, output_path.parent, manifest, story, summary_rows)
    output_path.write_text(html_out, encoding="utf-8")
    print(f"Dashboard gerado em {output_path}")


if __name__ == "__main__":
    main()
