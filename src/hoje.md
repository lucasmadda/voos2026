---
title: Hoje e amanhã
---

# Hoje e amanhã

```js
import {rows} from "./components/arrow.js";
import {kpiGrid, badge, legend} from "./components/kpi.js";
import {statusGroup, STATUS_ORDER, STATUS_LABEL, STATUS_COLOR, CARRIER_ORDER} from "./components/palette.js";
import {fmtHHMM, fmtDate, fmtDateLong, fmtStamp, pct, fmtInt, fmtDelay, todaySaoPaulo} from "./components/format.js";
import {flightsTimeline} from "./components/dayTimeline.js";
import {severityStrip} from "./components/weatherStrip.js";
import {fetchFraportLive} from "./components/fraportLive.js";
```

```js
const asof = await FileAttachment("./data/live/asof.json").json();
const inmet = await FileAttachment("./data/live/inmet_alerts.json").json();
const latest = rows(await FileAttachment("./data/live/fraport_latest.parquet").parquet());
const events = rows(await FileAttachment("./data/live/fraport_events.parquet").parquet());
const metar = rows(await FileAttachment("./data/live/metar_recent.parquet").parquet());
const siros = rows(await FileAttachment("./data/live/siros_today.parquet").parquet());
const airports = rows(await FileAttachment("./data/dims/dim_airport.parquet").parquet());
const byIcao = new Map(airports.map((a) => [a.icao, a]));
const byIata = new Map(airports.filter((a) => a.iata).map((a) => [a.iata, a]));
const NE = new Set(airports.filter((a) => a.is_ne).map((a) => a.icao));
const HUBS = new Set(airports.filter((a) => a.is_hub).map((a) => a.icao));
const SITE_ICAO = {POA: "SBPA", FOR: "SBFZ"};
const SITE_NAME = {POA: "Porto Alegre (SBPA)", FOR: "Fortaleza (SBFZ)"};
```

<div class="note">
Status <strong>provisório</strong>, lido do painel público do operador do aeroporto (Fraport Brasil) em
${fmtStamp(asof?.fraport?.POA?.fetched_at)} para POA e ${fmtStamp(asof?.fraport?.FOR?.fetched_at)} para FOR.
O registro oficial é o VRA da ANAC, publicado só no fim do mês seguinte. Um cancelamento no painel não informa motivo.
</div>

```js
const site = view(Inputs.radio(["POA", "FOR"], {label: "Aeroporto", value: "POA", format: (s) => SITE_NAME[s]}));
```

```js
const today = todaySaoPaulo();
const days = [...new Set(latest.filter((d) => d.site === site).map((d) => d.sched_date_local))].sort();
const dayLabel = (d) => `${fmtDateLong(d)}${d === today ? " · hoje" : d === todaySaoPaulo(1) ? " · amanhã" : d === todaySaoPaulo(-1) ? " · ontem" : ""}`;
const day = view(Inputs.radio(days, {label: "Dia", value: days.includes(today) ? today : days.at(-1), format: dayLabel}));
const direction = view(Inputs.radio(new Map([["Partidas", "dep"], ["Chegadas", "arr"]]), {label: "Sentido", value: "dep"}));
const scope = view(Inputs.radio(new Map([["Todos", "all"], ["Nordeste", "NE"], ["Hubs (conexões)", "hub"], ["Internacional", "intl"]]), {label: "Destino / origem", value: "all"}));
const carrier = view(Inputs.radio(["todas", ...CARRIER_ORDER], {label: "Companhia", value: "todas"}));
```

```js
function enrich(d) {
  const ap = (d.other_icao && byIcao.get(d.other_icao)) || byIata.get(d.other_iata) || null;
  return {
    ...d,
    other_icao: d.other_icao ?? ap?.icao ?? null,
    other_regiao: ap?.regiao ?? null,
    other_uf: d.other_uf ?? ap?.uf ?? null,
    other_city: d.other_city ?? ap?.municipio_servido ?? d.other_iata,
    is_ne: ap ? NE.has(ap.icao) : false,
    is_hub: ap ? HUBS.has(ap.icao) : false,
    is_intl: ap ? ap.country !== "BR" : !d.other_uf,
    group: statusGroup(d)
  };
}
const all = latest.map(enrich);
const flights = all
  .filter((d) => d.site === site && d.sched_date_local === day && d.direction === direction)
  .filter((d) => scope === "all" || (scope === "NE" && d.is_ne) || (scope === "hub" && d.is_hub) || (scope === "intl" && d.is_intl))
  .filter((d) => carrier === "todas" || d.carrier_group === carrier)
  .sort((a, b) => (a.sched_local < b.sched_local ? -1 : 1));
const n = flights.length;
const nCanc = flights.filter((d) => d.group === "cancelado").length;
const nAtr = flights.filter((d) => d.group === "atrasado").length;
const nAlt = flights.filter((d) => d.group === "alternado").length;
const nDone = flights.filter((d) => d.group === "realizado").length;
```

## ${direction === "dep" ? "Partidas" : "Chegadas"} · ${SITE_NAME[site]} · ${fmtDateLong(day)}

```js
display(kpiGrid([
  {label: direction === "dep" ? "partidas previstas" : "chegadas previstas", value: fmtInt(n), sub: scope === "all" ? "todas as rotas" : scope === "NE" ? "só Nordeste" : scope === "hub" ? "só hubs de conexão" : "só internacionais"},
  {label: "canceladas", value: fmtInt(nCanc), sub: pct(nCanc, n), tone: nCanc ? "critical" : ""},
  {label: "atrasadas ≥ 30 min", value: fmtInt(nAtr), sub: "estimado − previsto original", tone: nAtr ? "warning" : ""},
  {label: "alternadas", value: fmtInt(nAlt), sub: nAlt ? "desviadas para outro aeródromo" : "—", tone: nAlt ? "serious" : ""},
  {label: direction === "dep" ? "já decolaram" : "já pousaram", value: fmtInt(nDone), sub: pct(nDone, n)}
]));
```

```js
const metarSite = metar.filter((d) => d.icao === SITE_ICAO[site]);
display(flightsTimeline(flights, metarSite, {day, width, airportLabel: SITE_ICAO[site]}));
```

<p class="muted small">Pontos: voos previstos, por companhia, no horário previsto original (relógio local). Fundo: pior condição METAR em ${SITE_ICAO[site]} em cada hora (claro = VMC, escuro = abaixo dos mínimos). Passe o mouse para o METAR cru.</p>

```js
display(Inputs.table(flights, {
  columns: ["flight_code_raw", "carrier_group", "other_city", "other_uf", "other_regiao", "sched_local", "est_local", "delay_min", "status_raw", "gate"],
  header: {flight_code_raw: "voo", carrier_group: "cia", other_city: direction === "dep" ? "destino" : "origem", other_uf: "UF", other_regiao: "região", sched_local: "previsto", est_local: "estimado", delay_min: "atraso", status_raw: "status", gate: "portão"},
  format: {sched_local: fmtHHMM, est_local: fmtHHMM, delay_min: fmtDelay, status_raw: (s, i, data) => badge(data[i].group, s), other_regiao: (r) => r ?? "—", other_uf: (u) => u ?? "—"},
  width: {flight_code_raw: 70, carrier_group: 60, other_uf: 40, other_regiao: 60, sched_local: 70, est_local: 70, delay_min: 90, gate: 60},
  rows: 40, layout: "auto", sort: "sched_local"
}));
```

## Condições METAR por hora — ${fmtDate(day)}

```js
const neWithFlights = [...new Set(all.filter((d) => d.site === site && d.sched_date_local === day && d.is_ne && d.other_icao).map((d) => d.other_icao))].sort();
const stations = [SITE_ICAO[site], ...neWithFlights.filter((s) => s !== SITE_ICAO[site])];
const labels = Object.fromEntries(stations.map((s) => [s, `${s} · ${byIcao.get(s)?.municipio_servido ?? ""}`]));
display(severityStrip(metar, {stations, day, width, labels}));
```

<p class="muted small">Pior leitura METAR/SPECI de cada hora local. IMC = visibilidade &lt; 5 000 m ou teto &lt; 1 500 ft; vermelho = &lt; 1 500 m ou &lt; 600 ft, convecção (TS/CB/GR/SQ) ou rajada ≥ 25 kt; abaixo CAT I = &lt; 550 m ou &lt; 200 ft. Fonte: DECEA via Iowa Environmental Mesonet.</p>

## Trechos diretos ${SITE_ICAO[site]} ↔ Nordeste na janela do painel

```js
const neLegs = all.filter((d) => d.site === site && d.is_ne).sort((a, b) => (a.sched_local < b.sched_local ? -1 : 1));
display(Inputs.table(neLegs, {
  columns: ["sched_date_local", "direction", "flight_code_raw", "carrier_group", "other_city", "other_uf", "sched_local", "est_local", "delay_min", "status_raw"],
  header: {sched_date_local: "dia", direction: "sentido", flight_code_raw: "voo", carrier_group: "cia", other_city: "cidade", other_uf: "UF", sched_local: "previsto", est_local: "estimado", delay_min: "atraso", status_raw: "status"},
  format: {sched_date_local: fmtDate, direction: (d) => (d === "dep" ? "partida" : "chegada"), sched_local: fmtHHMM, est_local: fmtHHMM, delay_min: fmtDelay, status_raw: (s, i, data) => badge(data[i].group, s)},
  rows: 20, layout: "auto"
}));
```

```js
const sirosNE = siros.filter((d) => d.origin_icao === SITE_ICAO[site] && NE.has(d.dest_icao));
const hubLegs = all.filter((d) => d.site === site && d.sched_date_local === day && d.direction === "dep" && d.is_hub);
const hubByGroup = d3.rollup(hubLegs, (v) => v.length, (d) => d.group);
```

<div class="grid grid-cols-2">
  <div class="card">
    <h3>Malha registrada na ANAC (SIROS) para ${fmtDate(siros[0]?.snapshot_date)}</h3>
    <p class="muted small">Trechos ${SITE_ICAO[site]} → Nordeste planejados no snapshot diário do SIROS (UTC). O que estava na malha e sumiu do painel é remoção prévia, não cancelamento.</p>
    ${sirosNE.length ? Inputs.table(sirosNE, {columns: ["carrier_icao", "flight_number", "equipment", "seats", "dest_icao", "sched_dep_utc", "codeshare"], header: {carrier_icao: "cia", flight_number: "voo", equipment: "equip.", seats: "assentos", dest_icao: "destino", sched_dep_utc: "partida (UTC)", codeshare: "codeshare"}, format: {sched_dep_utc: (s) => s?.slice(11, 16)}, rows: 10}) : html`<p class="muted">nenhum trecho direto registrado</p>`}
  </div>
  <div class="card">
    <h3>Conexões possíveis: partidas para hubs em ${fmtDate(day)}</h3>
    <p class="muted small">A maior parte das viagens para o Nordeste conecta em GRU, CGH, VCP, BSB, GIG ou CNF. Um painel de aeroporto mostra só o primeiro trecho.</p>
    ${kpiGrid(STATUS_ORDER.filter((g) => hubByGroup.get(g)).map((g) => ({label: STATUS_LABEL[g], value: fmtInt(hubByGroup.get(g) ?? 0), tone: g === "cancelado" ? "critical" : g === "atrasado" ? "warning" : g === "alternado" ? "serious" : ""})))}
    <p class="muted small">${fmtInt(hubLegs.length)} partidas para hubs no dia.</p>
  </div>
</div>

## Mudanças de status observadas no painel

```js
const siteEvents = events
  .filter((d) => d.site === site && d.field !== "first_seen")
  .sort((a, b) => (a.changed_at < b.changed_at ? 1 : -1));
display(siteEvents.length
  ? Inputs.table(siteEvents, {
      columns: ["changed_at", "direction", "flight_code_raw", "carrier_group", "other_iata", "sched_local", "field", "from_value", "to_value"],
      header: {changed_at: "observado em", direction: "sentido", flight_code_raw: "voo", carrier_group: "cia", other_iata: "para/de", sched_local: "previsto", field: "campo", from_value: "de", to_value: "para"},
      format: {changed_at: fmtStamp, direction: (d) => (d === "dep" ? "partida" : "chegada"), sched_local: (s) => `${fmtDate(s?.slice(0, 10))} ${fmtHHMM(s)}`},
      rows: 20, layout: "auto"
    })
  : html`<p class="muted">Ainda não há transições registradas: elas aparecem conforme o capturador (a cada 15 min) observa mudanças de status ou de horário estimado. Snapshots de ${site}: ${asof?.fraport?.[site]?.n_snapshots ?? 0}.</p>`);
```

## Avisos meteorológicos ativos (INMET)

```js
const UF_SITE = {POA: "RS", FOR: "CE"};
const NE_UFS = new Set(["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"]);
const alerts = (inmet?.alerts ?? []).filter((a) => (a.ufs ?? []).some((u) => u === UF_SITE[site] || NE_UFS.has(u)));
display(alerts.length
  ? html`<div>${alerts.map((a) => html`<div class="alert-card"><span class="sev">${a.severidade}</span> · ${a.descricao}<br><span class="muted small">${a.inicio} → ${a.fim} · ${(a.ufs ?? []).join(", ")} · ${fmtInt(a.n_municipios)} municípios${a.riscos ? ` · ${typeof a.riscos === "string" ? a.riscos : ""}` : ""}</span></div>`)}</div>`
  : html`<p class="muted">Nenhum aviso ativo para ${UF_SITE[site]} ou Nordeste no snapshot de ${fmtStamp(inmet?.fetched_at)}.</p>`);
```

## Painel ao vivo (opcional)

<p class="muted small">Busca o painel da Fraport direto do seu navegador (próximas horas, sem histórico). Útil no dia da eleição; não substitui os snapshots arquivados.</p>

```js
const refresh = view(Inputs.button("Buscar painel ao vivo agora"));
```

```js
const live = refresh > 0 ? await fetchFraportLive(site) : null;
display(live
  ? html`<div><p class="muted small">Lido às ${live.fetched_at.toLocaleTimeString("pt-BR", {timeZone: "America/Sao_Paulo"})} (horário de Brasília) · ${live.rows.length} voos</p>
      ${Inputs.table(live.rows.filter((d) => d.direction === "dep"), {columns: ["flight_code_raw", "carrier_group", "other_city", "other_uf", "scheduled_time", "estimated_time", "status_raw", "gate"], header: {flight_code_raw: "voo", carrier_group: "cia", other_city: "destino", other_uf: "UF", scheduled_time: "previsto", estimated_time: "estimado", status_raw: "status", gate: "portão"}, rows: 30})}</div>`
  : html`<p class="muted small">clique para buscar</p>`);
```

<p class="muted small">Fontes desta página: painel de voos da Fraport Brasil (POA/FOR), SIROS/ANAC (malha diária), DECEA via Iowa Environmental Mesonet (METAR/SPECI), INMET (avisos). Horários no relógio local do aeroporto (UTC−3). Veja <a href="./metodologia">metodologia e fontes</a>.</p>
