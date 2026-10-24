import * as d3 from "npm:d3";

// Datas locais "ingênuas" (YYYY-MM-DDTHH:MM:SS) são lidas como UTC de propósito: assim o
// relógio de parede do aeroporto é preservado independentemente do fuso do leitor.
export const parseLocal = d3.utcParse("%Y-%m-%dT%H:%M:%S");
export const parseUtc = d3.utcParse("%Y-%m-%dT%H:%M:%SZ");
export const parseDate = d3.utcParse("%Y-%m-%d");
export const fmtHHMM = (s) => (s ? d3.utcFormat("%H:%M")(parseLocal(s)) : "—");
export const fmtDate = (s) => (s ? d3.utcFormat("%d/%m")(parseDate(s)) : "—");
export const fmtDateLong = (s) => {
  if (!s) return "—";
  const d = parseDate(s);
  const dias = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];
  return `${dias[d.getUTCDay()]}, ${d3.utcFormat("%d/%m/%Y")(d)}`;
};
export const fmtStamp = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", {timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"}) + " (horário de Brasília)";
};
export const pct = (num, den, digits = 1) => (den ? `${((100 * num) / den).toFixed(digits).replace(".", ",")} %` : "—");
export const fmtInt = (n) => (n == null ? "—" : n.toLocaleString("pt-BR"));
export const fmtDelay = (m) => (m == null ? "—" : m > 0 ? `+${m} min` : m < 0 ? `${m} min` : "no horário");

// Dia local de hoje em America/Sao_Paulo como "YYYY-MM-DD"
export function todaySaoPaulo(offsetDays = 0) {
  const now = new Date(Date.now() + offsetDays * 864e5);
  const parts = new Intl.DateTimeFormat("en-CA", {timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit"}).formatToParts(now);
  const get = (t) => parts.find((p) => p.type === t).value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}
