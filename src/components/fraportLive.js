// Busca o painel da Fraport direto do browser (CORS verificado) para um painel "ao vivo".
const SITES = {POA: "portoalegre-airport.com.br", FOR: "fortaleza-airport.com.br"};
const URL = "https://api-site.fraport-brasil.com/api/flight?page=1&per_page=300&home=0&all=0&language_slug=pt";

export async function fetchFraportLive(site = "POA") {
  const r = await fetch(URL, {headers: {"X-Current-Site-Id": SITES[site]}});
  if (!r.ok) throw new Error(`Fraport ${site}: HTTP ${r.status}`);
  const payload = await r.json();
  return {fetched_at: new Date(), site, rows: normalizeLive(payload, site)};
}

function* iter(section) {
  if (Array.isArray(section)) for (const f of section) yield f;
  else if (section && typeof section === "object") for (const items of Object.values(section)) for (const f of items ?? []) yield f;
}

const CARRIER = {G3: "GOL", AD: "Azul", "2F": "Azul", LA: "LATAM", JJ: "LATAM"};

export function normalizeLive(payload, site) {
  const out = [];
  for (const direction of ["departures", "arrivals"]) {
    for (const f of iter(payload?.[direction])) {
      const place = direction === "departures" ? f.destination : f.origin;
      const name = place?.name ?? "";
      const m = /^([A-Z]{2}) - (.+)$/.exec(name);
      const iata = (f.flight ?? "").slice(0, 2);
      const sched = (f.original_scheduled_time ?? "").replace(" ", "T");
      out.push({
        site,
        direction: direction === "departures" ? "dep" : "arr",
        flight_code_raw: f.flight,
        carrier_group: CARRIER[iata] ?? "outras",
        airline_name: f.airline?.text ?? "",
        other_iata: place?.iata ?? "",
        other_city: m ? m[2] : name,
        other_uf: m ? m[1] : null,
        sched_local: sched,
        sched_date_local: sched.slice(0, 10),
        scheduled_time: f.scheduled_time,
        estimated_time: f.estimated_time,
        status_raw: f.status?.text ?? "",
        gate: f.gate ?? ""
      });
    }
  }
  return out.sort((a, b) => (a.sched_local < b.sched_local ? -1 : 1));
}
