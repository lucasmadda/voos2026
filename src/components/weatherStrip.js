import * as Plot from "npm:@observablehq/plot";
import {parseUtc, parseDate} from "./format.js";
import {SEVERITY_COLOR, SEVERITY_LABEL} from "./palette.js";

/** Faixa aeroporto × hora local com a pior condição METAR da hora (sequencial, 1 matiz). */
export function severityStrip(metar, {stations, day, width, tzOffsetHours = -3, labels = {}} = {}) {
  const dayStart = parseDate(day);
  const dayEnd = new Date(dayStart.getTime() + 864e5);
  const cells = new Map();
  for (const d of metar) {
    if (!stations.includes(d.icao)) continue;
    const t = new Date(parseUtc(d.valid_utc).getTime() + tzOffsetHours * 3600e3);
    if (t < dayStart || t >= dayEnd) continue;
    const hour = t.getUTCHours();
    const key = `${d.icao}|${hour}`;
    const prev = cells.get(key);
    if (!prev || (d.severity ?? 0) > (prev.severity ?? 0)) cells.set(key, {...d, hour});
  }
  const data = [...cells.values()];
  return Plot.plot({
    width,
    height: 40 + 26 * stations.length,
    marginLeft: 120,
    marginRight: 10,
    padding: 0.08,
    style: {fontSize: "12px"},
    x: {domain: Array.from({length: 24}, (_, i) => i), tickFormat: (h) => (h % 3 === 0 ? `${String(h).padStart(2, "0")}h` : ""), label: null},
    y: {domain: stations, label: null, tickFormat: (s) => labels[s] ?? s},
    color: {domain: [0, 1, 2, 3], range: SEVERITY_COLOR, legend: true, tickFormat: (s) => SEVERITY_LABEL[s]},
    marks: [
      Plot.cell(data, {
        x: "hour", y: "icao", fill: "severity", inset: 1, rx: 2, tip: true,
        title: (d) => `${d.icao} ${String(d.hour).padStart(2, "0")}h local · ${SEVERITY_LABEL[d.severity]}\nvis ${d.vis_m ?? "—"} m · teto ${d.ceiling_ft ?? "—"} ft${d.gust_kt ? ` · rajada ${d.gust_kt} kt` : ""}\n${d.wx || "sem fenômeno"}\n${d.metar_raw ?? ""}`
      })
    ]
  });
}
