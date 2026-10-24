import * as Plot from "npm:@observablehq/plot";
import {parseLocal, parseUtc, parseDate, fmtHHMM, fmtDelay} from "./format.js";
import {STATUS_ORDER, STATUS_LABEL, STATUS_COLOR, CARRIER_ORDER, statusGroup, severityColor, SEVERITY_LABEL} from "./palette.js";

/**
 * Linha do tempo do dia: faixas horárias de condição METAR (fundo) + voos como pontos por companhia.
 * flights: linhas de fraport_latest já filtradas (um dia, um sentido); metar: linhas de metar_recent do aeroporto.
 * Eixo x em "horário de parede" local (datas locais lidas como UTC — ver format.js).
 */
export function flightsTimeline(flights, metar, {day, width, tzOffsetHours = -3, airportLabel = "SBPA"} = {}) {
  const dayStart = parseDate(day);
  const dayEnd = new Date(dayStart.getTime() + 864e5);
  // METAR vem em UTC → desloca para o relógio local do aeroporto (UTC−3 em POA/FOR)
  const bands = metar
    .map((d) => ({...d, t: new Date(parseUtc(d.valid_utc).getTime() + tzOffsetHours * 3600e3)}))
    .filter((d) => d.t >= new Date(dayStart.getTime() - 3600e3) && d.t <= dayEnd)
    .sort((a, b) => a.t - b.t)
    .map((d, i, arr) => ({...d, t1: arr[i + 1]?.t ?? new Date(Math.min(d.t.getTime() + 3600e3, dayEnd.getTime()))}));
  const pts = flights.map((d) => ({...d, t: parseLocal(d.sched_local), group: statusGroup(d)}));
  const lanes = CARRIER_ORDER.filter((g) => pts.some((p) => p.carrier_group === g));
  return Plot.plot({
    width,
    height: 70 + 34 * Math.max(1, lanes.length),
    marginLeft: 56,
    marginRight: 16,
    style: {fontSize: "12px"},
    x: {type: "utc", domain: [dayStart, dayEnd], tickFormat: "%H:%M", ticks: 12, label: null, grid: true},
    y: {domain: lanes, label: null, padding: 0.5},
    color: {domain: STATUS_ORDER, range: STATUS_ORDER.map((s) => STATUS_COLOR[s]), legend: true, tickFormat: (s) => STATUS_LABEL[s]},
    marks: [
      Plot.rect(bands, {
        x1: "t", x2: "t1", fill: (d) => severityColor(d.severity), fillOpacity: 0.22,
        title: (d) => `${airportLabel} METAR ${fmtHHMM(d.valid_utc.replace("Z", "")) } UTC · ${SEVERITY_LABEL[d.severity]}\nvis ${d.vis_m ?? "—"} m · teto ${d.ceiling_ft ?? "—"} ft · ${d.wx || "sem fenômeno"}\n${d.metar_raw ?? ""}`
      }),
      Plot.dot(pts, {
        x: "t", y: "carrier_group", fill: "group", r: 6.5, stroke: "var(--theme-background)", strokeWidth: 1.5,
        sort: {channel: "fill", order: STATUS_ORDER},
        tip: true,
        title: (d) => `${d.flight_code_raw} → ${d.other_city ?? d.other_iata} (${d.other_iata})\nprevisto ${fmtHHMM(d.sched_local)} · estimado ${fmtHHMM(d.est_local)} · ${fmtDelay(d.delay_min)}\nstatus: ${d.status_raw}`
      }),
      Plot.text(pts.filter((d) => d.group === "cancelado" || d.group === "alternado"), {
        x: "t", y: "carrier_group", text: "flight_code_raw", dy: -14, fontSize: 11, fill: "var(--theme-foreground)"
      })
    ]
  });
}
