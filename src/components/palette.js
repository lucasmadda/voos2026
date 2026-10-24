// Paleta: cor segue a entidade (companhia) ou o estado (status) — nunca o rank.
function cssVar(name, fallback) {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export const CARRIER_COLOR = {
  Azul: cssVar("--series-1", "#3987e5"),
  GOL: cssVar("--series-2", "#d95926"),
  LATAM: cssVar("--series-3", "#199e70"),
  outras: cssVar("--series-other", "#898781")
};
export const CARRIER_ORDER = ["GOL", "Azul", "LATAM", "outras"];
export const carrierColor = (g) => CARRIER_COLOR[g] ?? CARRIER_COLOR.outras;

// Grupos de status exibidos (derivados de status_canon + atraso)
export const STATUS_ORDER = ["previsto", "realizado", "atrasado", "alternado", "cancelado"];
export const STATUS_LABEL = {
  previsto: "previsto / em solo",
  realizado: "decolou / pousou",
  atrasado: "atrasado ≥ 30 min",
  alternado: "alternado",
  cancelado: "cancelado"
};
export const STATUS_COLOR = {
  previsto: cssVar("--neutral-scheduled", "#5a5955"),
  realizado: cssVar("--neutral-done", "#898781"),
  atrasado: cssVar("--status-warning", "#fab219"),
  alternado: cssVar("--status-serious", "#ec835a"),
  cancelado: cssVar("--status-critical", "#d03b3b")
};
export const statusColor = (s) => STATUS_COLOR[s] ?? STATUS_COLOR.previsto;

/** Rótulo curto do status cru do painel (cabe na coluna da tabela; o cru fica no title). */
const SHORT_STATUS = {
  "Previsto": "previsto", "Confirmado": "confirmado", "Embarque próximo": "embarque", "Embarque": "embarque",
  "Última chamada": "embarque", "Embarque encerrado": "embarque", "Decolagem": "decolou", "Pousado": "pousou",
  "Atrasado": "atrasado", "Cancelado": "cancelado", "Alternado": "alternado",
  "On time": "previsto", "Confirmed": "confirmado", "Boarding": "embarque", "Final Call": "embarque",
  "Gate closed": "embarque", "Departed": "decolou", "Landed": "pousou", "Delayed": "atrasado",
  "Cancelled": "cancelado", "Diverted": "alternado"
};
export const shortStatus = (raw) => SHORT_STATUS[raw] ?? (raw ?? "—").toLowerCase();

/** Agrupa um voo normalizado da Fraport em um dos 5 grupos de status. */
export function statusGroup(d) {
  const c = d.status_canon;
  if (c === "cancelled") return "cancelado";
  if (c === "diverted") return "alternado";
  if (c === "delayed" || (d.delay_min != null && d.delay_min >= 30)) return "atrasado";
  if (c === "departed" || c === "landed" || c === "operated") return "realizado";
  return "previsto";
}

// Severidade METAR 0–3: escala sequencial de um matiz (claro = VMC, escuro = pior)
export const SEVERITY_LABEL = ["VMC", "IMC", "vermelho", "abaixo CAT I"];
export const SEVERITY_COLOR = [
  cssVar("--seq-100", "#cde2fb"),
  cssVar("--seq-250", "#86b6ef"),
  cssVar("--seq-550", "#1c5cab"),
  cssVar("--seq-700", "#0d366b")
];
export const severityColor = (s) => SEVERITY_COLOR[Math.max(0, Math.min(3, s ?? 0))];
