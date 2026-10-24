import {html} from "npm:htl";

/** Cartão de indicador: valor grande, rótulo em caixa alta, linha de apoio. */
export function kpi({label, value, sub = "", tone = ""}) {
  return html`<div class="kpi ${tone ? `tone-${tone}` : ""}">
    <div class="kpi-label">${label}</div>
    <div class="kpi-value">${value}</div>
    ${sub ? html`<div class="kpi-sub">${sub}</div>` : ""}
  </div>`;
}

export function kpiGrid(items) {
  return html`<div class="kpi-grid">${items.map(kpi)}</div>`;
}

export function badge(group, label) {
  return html`<span class="badge badge-${group}">${label ?? group}</span>`;
}

export function legend(entries) {
  return html`<div class="legend">${entries.map(([label, color]) => html`<span><span class="swatch" style="background:${color}"></span>${label}</span>`)}</div>`;
}
