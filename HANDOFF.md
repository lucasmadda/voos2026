# HANDOFF — voos2026

Estado em 24/10/2026 ~20:50 BRT, escrito pela sessão paralela ("Chat lateral") ao passar a
execução para a sessão principal. Plano aprovado:
`~/.claude/plans/https-openflightapi-com-docs-est-se-fala-refactored-sphinx.md`.

## Pronto e verificado

- **Repo** próprio em `/Users/lucasgomesmaddalena/voos2026` (branch `main`), remoto público
  `https://github.com/lucasmadda/voos2026`. A pasta está excluída do repo git da home
  (`voos2026/` em `~/.git/info/exclude`). **Antes de todo push: `git pull --rebase origin main`**
  (o bot de captura commita em `main` a cada 30 min).
- **Ambiente:** `.venv` (Python 3.13) com `duckdb==1.5.6`, `pyarrow==26.0.0`, `httpx==0.28.1`,
  `certifi`, `remotezip==0.12.6`, `numpy`, `pytest`; pacote `voos` instalado em modo editável
  (`pyproject.toml`, código em `pipeline/voos`). Node: `@observablehq/framework@1.13.4` em
  `node_modules` (`package.json`, `package-lock.json`). `scripts/bootstrap.sh` recria tudo.
- **Core do pipeline:** `pipeline/voos/{config,tz,keys,http,io,vocab,guards,capture}.py`.
  Testes `tests/test_keys.py` e `tests/test_tz.py` passam (`.venv/bin/pytest -q`).
- **Captura (urgente, rodando):** `python -m voos.capture --site POA --site FOR --inmet --siros-diario`
  → `data/archive/fraport/{POA,FOR}/YYYY-MM-DD/<ts>Z.json.gz` (ícones SVG removidos, ~9 KB cada),
  `data/archive/inmet/YYYY-MM-DD/<ts>.json.gz` (só quando o corpo muda), `data/archive/siros/diario/diario_YYYY-MM-DD.csv.gz`.
  Verificado em todos os snapshots: `G31979 → SSA 2026-10-24 10:30 Cancelado`; AD4151 → REC operou em 23 e 24 e está previsto em 25.
  - **launchd (local):** `~/Library/LaunchAgents/com.lucasmadda.voos2026.capture.plist`, `StartInterval 900`
    (15 min), `RunAtLoad false`, logs em `data/raw/logs/capture.{out,err}.log`. Estado:
    `launchctl print gui/$(id -u)/com.lucasmadda.voos2026.capture`. Disparo manual:
    `launchctl kickstart gui/$(id -u)/com.lucasmadda.voos2026.capture`. Não dispara com o Mac dormindo.
  - **GitHub Actions (nuvem):** `.github/workflows/capture.yml`, cron `7,37 * * * *`, commita o arquivo
    com o usuário `voos2026-bot`. Primeiro run manual OK (commit `f42a684`). É a captura robusta.
- **Front (Dia 0):** `observablehq.config.js` (interpretador `.venv/bin/python` para `.py`, páginas,
  rodapé), `src/style.css` (importa `observablehq:default.css` + `theme-near-midnight` + `alt` +
  `wide` e define os tokens da paleta do skill dataviz: `--series-1..8`, `--status-*`, `--seq-*`),
  componentes `src/components/{arrow,format,palette,kpi,dayTimeline,weatherStrip,fraportLive}.js`,
  página **`src/hoje.md` completa mas NÃO testada no browser** (KPIs, linha do tempo voos × METAR,
  tabela, faixa METAR por hora, trechos NE, SIROS do dia, conexões para hubs, transições de status,
  avisos INMET, painel ao vivo via fetch com `X-Current-Site-Id`), `src/index.md`, stubs
  `rotas/clima/eleitoral/baselines/voo-1979.md`, `src/metodologia.md` inicial.
  `.claude/launch.json` → preview na porta 3000 (`npm run dev` = `observable preview`).
- **Ontologia Nível 1:** `ontology/status_vocab.csv` (30 termos: Fraport pt/en, VRA, SIROS,
  FlightAware, AeroDataBox), `ontology/modelo-conceitual.md` (classes gUFO, relações, diagrama
  Mermaid, glossário, guardrails), `voos/vocab.py` (`canon()`, `unmapped()`), `voos/guards.py`
  (`enforce()` com regras 1, 2, 6 + status; `VOOS_GUARDS_STRICT=0` desliga). **Os marts ainda não
  chamam `guards.enforce`** — ligar no passo 6b.
- `scripts/validate_palette.js` (cópia do validador do skill dataviz; `npm run palette -- "<hex,…>" --mode dark`).
- `.github/workflows/deploy.yml` escrito (build + Pages) com o gatilho de push **desligado** até o
  Pages ser habilitado (ver comandos).

## Pela metade

Três agentes em paralelo (workflow `voos-dia0-loaders`) estavam construindo, quando o handoff foi
pedido, os loaders abaixo. **Confira o que existe em disco e rode cada shim antes de confiar**;
a seção "Resultado dos loaders" no fim deste arquivo registra o que o workflow reportou.

| Área | Arquivos | Shims (src/data/…) |
|---|---|---|
| METAR (IEM) | `pipeline/voos/sources/iem.py`, `pipeline/voos/marts/weather.py`, `tests/test_weather.py` | `live/metar_recent.parquet.py`, `hist/metar_hourly.parquet.py`, `hist/weather_daily.parquet.py` |
| Dimensão de aeroportos | `pipeline/voos/sources/anac_aerodromos.py`, `pipeline/voos/sources/ourairports.py`, `pipeline/voos/marts/dims.py`, `tests/test_dims.py` | `dims/dim_airport.parquet.py` |
| Marts ao vivo | `pipeline/voos/marts/live.py`, `tests/test_live.py` | `live/fraport_latest.parquet.py`, `live/fraport_events.parquet.py`, `live/siros_today.parquet.py`, `live/inmet_alerts.json.py`, `live/asof.json.py` |

Contrato que `src/hoje.md` espera (nomes exatos de colunas):
- `fraport_latest`: `site, airport_icao, direction ('dep'|'arr'), flight_code_raw, carrier_iata, flight_number, carrier_icao, carrier_group ('GOL'|'Azul'|'LATAM'|'outras'), airline_name, other_iata, other_name_raw, other_city, other_uf, other_icao, sched_local, sched_utc, sched_date_local, sched_hour_local, est_local, est_utc, delay_min, status_raw, status_canon, event_class, status_kind, confidence, is_disruption, gate, fraport_id, event_key, flight_key, source, fetched_at, first_seen_at, n_snapshots, prev_status_raw, status_changed_at`.
- `fraport_events`: `site, direction, flight_code_raw, carrier_group, carrier_icao, other_iata, other_uf, sched_local, sched_date_local, changed_at, field ('first_seen'|'status'|'estimated'|'disappeared'), from_value, to_value, status_canon_to`.
- `metar_recent`: `icao, valid_utc, report_type, vis_m, ceiling_ft, sky, wx, wind_dir, wind_kt, gust_kt, temp_c, dewp_c, pressure_hpa, metar_raw, imc, red, below_cat1, convective, gusty, severity (0–3), severity_label, source`.
- `dim_airport`: `icao, iata, name, country, municipio, municipio_servido, uf, uf_nome, regiao, regiao_nome, lat, lon, tz, ciad, scheduled_service, is_focus_origin, is_ne, is_hub, source`.
- `siros_today`: `snapshot_date, carrier_icao, carrier_group, flight_number, number_prefix, equipment, seats, n_siros, data_registro_utc, inicio_operacao, fim_operacao, natureza, tipo_servico, objeto, leg_number, origin_icao, origin_name, dest_icao, dest_name, sched_dep_utc, sched_arr_utc, operates_today, codeshare, flight_key, is_focus_leg`.
- `inmet_alerts.json`: `{fetched_at, source, n_alerts, alerts:[{id, descricao, severidade, inicio, fim, estados, ufs[], n_municipios, geocodes[], riscos, cor}]}`.
- `asof.json`: `{built_at, fraport:{POA:{fetched_at, snapshot_file, n_snapshots, n_dep, n_arr, dates}, FOR:{…}}, inmet:{fetched_at, n_alerts}, siros_diario:{snapshot_date, n_legs}}`.

## Decisões tomadas fora do texto do plano

- **Chave de evento da Fraport = `site|direction|flight_code_raw|sched_local`.** O `id` do painel
  NÃO é estável (o G31979 de 24/10 veio com três ids diferentes em três consultas).
- **Datas e horas nos marts são STRINGS ISO** (`*_utc` com `Z`, `*_local` ingênuo no relógio do
  aeroporto, `*_date_local` `YYYY-MM-DD`), nunca tipos timestamp do Arrow: o Arrow JS devolve
  timestamps como números e int64 como BigInt. `src/components/arrow.js` converte BigInt → Number.
  `format.js` lê os `_local` como UTC de propósito (preserva o relógio de parede independentemente
  do fuso do leitor) e usa `x: {type: "utc"}` no Plot.
- **Nomes de marts diferentes do plano:** `src/data/live/{fraport_latest,fraport_events,siros_today}.parquet`,
  `live/{asof,inmet_alerts}.json`, `live/metar_recent.parquet`, `dims/dim_airport.parquet`,
  `hist/{metar_hourly,weather_daily}.parquet` (o plano fala em `fraport_flights`, `dim_airports`,
  `sources`). `sources`/`status_vocab` como marts ainda não existem.
- **Sem polars/pandas:** DuckDB SQL (dialeto 1.x, o browser roda core 1.1.1) + pyarrow.
- **User-Agent `voos2026/0.1`** sem URL/parênteses: o WAF do SIROS devolve "Request Rejected" para
  UA com URL. `capture.py` é só stdlib (urllib + `certifi` se houver, fallback `curl` porque o TLS do
  Python do python.org falha sem certificados) e trata corpo HTML como erro.
- **SIROS diário:** a série datada `diario/serie/2026/diario_YYYY-MM-DD.csv` é a fonte primária;
  `diario.csv` (sem data) devolveu "Request Rejected" e ficou como fallback.
- **Paleta:** Azul = slot 1 (azul), GOL = slot 2 (laranja), LATAM = slot 3 (aqua), outras = cinza;
  status: cancelado = critical, atrasado (≥ 30 min) = warning, alternado = serious, realizado /
  previsto = cinzas neutros. Severidade METAR = rampa sequencial azul (`--seq-100/250/550/700`).
- `data/ref/carriers.csv` tem `2F→ACN` (Azul Conecta) e `2Z→PTB` (VoePass) **a verificar** no Dia 1;
  `data/ref/ufs.csv`, `holidays_br.csv`, `election_dates.csv`, `airports_override.csv` criados.
- Loaders: shims de 5 linhas em `src/data/...` que importam `voos.marts.*` e escrevem Parquet zstd no
  stdout (`voos.io.write_parquet_stdout`); logs só no stderr.

## Comandos úteis

```bash
cd /Users/lucasgomesmaddalena/voos2026
.venv/bin/pytest -q                                    # testes
.venv/bin/python src/data/live/fraport_latest.parquet.py > /tmp/x.parquet   # rodar um loader
npm run dev                                            # preview em http://localhost:3000/hoje
.venv/bin/python -m voos.capture --site POA --site FOR --inmet --siros-diario   # captura manual
gh run list --workflow=capture.yml --limit 5           # capturas na nuvem
# habilitar o GitHub Pages e religar o deploy por push:
gh api -X POST repos/lucasmadda/voos2026/pages -f build_type=workflow
#   → descomentar o bloco `push:` em .github/workflows/deploy.yml
```

## Próximos passos (do plano)

1. Testar `src/hoje.md` no preview e corrigir divergências de colunas com os marts.
2. Dia 1: 6b ligar `guards.enforce` nos marts; 7 `voos/vra.py` (VRA 2024-10→2026-09 + 2022-10);
   8 `voos/tse.py` + geo completo → `dim_airport` com `bucket_voto`; 9 `src/rotas.md`; 10 `src/index.md`.
3. Dia 2–3 conforme o plano; habilitar Pages e religar o deploy quando `npm run build` passar.

## Resultado dos loaders (workflow concluído às ~20:48 BRT)

Os três agentes terminaram e verificaram; relatório completo (verificações com saídas reais,
issues, schema) em `docs/loaders-report-dia0.md`. Suíte completa: **45 testes passam**
(`.venv/bin/pytest -q`). Resumo:

- **METAR/IEM — pronto.** `metar_recent` (8 dias, 28 estações, 5 450 reportes); `metar_hourly`
  2024-01-01→hoje = 705 632 reportes → 665 981 horas-estação em 2 min 42 s (32 downloads, cache
  reaproveitado na 2ª rodada, Parquet 1,9 MB); `weather_daily` 28 654 dias-estação. Verificado:
  SBPA 24/10 18Z vis 2 000 m / teto 900 ft, SPECI 16:08Z 3 000 m, 14Z e 19Z teto 700 ft, sem
  convecção; SBSV severidade 0 o dia todo; SBPA 24/10 `hours_imc = 12`; buraco da enchente
  (jun–set/2024) confirmado. Decisões: `report_type` é derivado (IEM não devolve a coluna; minuto :00
  = rotina, senão SPECI); `vis_m` é "encaixado" na resolução METAR (50 m abaixo de 800 m, 100 m
  acima; ≥ 6,2 mi → 10 000); convecção tokeniza grupos de tempo (TSRA, +TSRA, VCTS, RETS, SHGR, CB
  em camada, +RA) sem falsos positivos em 36 865 reportes.
- **dim_airport — pronto.** 4 439 linhas (496 BR da ANAC + 3 943 internacionais da OurAirports com
  voo regular), ICAO único, 0 IATA nulo entre foco/NE/hubs, 17 NE e 11 hubs presentes, toda linha BR
  com UF/região. Aliases de override (`municipio_fisico → municipio`). Expondo `uf_from_name`,
  `iata_to_icao` (4 150 pares). Internacionais ficam com `tz='UTC'` por enquanto.
- **Marts ao vivo — pronto.** `fraport_latest` 793 linhas (POA 483, FOR 310), `fraport_events` já
  com 6 mudanças de status e 1 de estimado nos 3 primeiros snapshots, `siros_today` 2 920 trechos
  (718 no escopo foco; 2 758 operam hoje), `inmet_alerts` 9 avisos (~150 KB por causa dos geocodes),
  `asof`. `other_icao` resolvido para 100 % das linhas. **`flight_key` nulo em 29/793 linhas**
  porque a cia não está em `data/ref/carriers.csv` (TP, CM, IB, AR, AF, LP, e Sideral `0S`) — ver
  pendências. Snapshot corrompido/parcial (escrito pelo launchd no meio) é pulado com log.

### Pendências pequenas apontadas pelos agentes (não feitas)

1. `data/ref/carriers.csv`: adicionar `0S→SID` (Sideral) e `TP→TAP`, `CM→CMP`, `IB→IBE`, `AR→ARG`,
   `AF→AFR`, `LP→LPE` para os 29 voos sem `flight_key`.
2. `voos/http.cached_download`: (a) quando o servidor não manda ETag nem Last-Modified (IEM), um
   arquivo com `max_age_hours=None` é re-baixado a cada chamada → opção `immutable`/"sem validadores
   + arquivo existe = fresco"; (b) `manifest.json` é lido/escrito sem lock (loaders rodam em paralelo
   no Framework) → escrita atômica (tmp + `os.replace`) ou lock; (c) o GET não passa por `get_bytes`
   (sem retry/backoff). `sources/iem.py` contorna (a) e (c) por conta própria.
3. Fraport: `'BH - Confins'` tem prefixo que não é UF (tratado: `other_uf=None`, `other_icao=SBCF`);
   `delay_min` em linhas `Decolagem/Pousado` usa o `estimated_time` como horário real (ex.: AD4151
   23/10 07:00 → est 09:00 = 120 min) — decidir se mostra ou zera para realizados.
4. INMET: `inicio`/`fim` sem fuso; assumido Brasília (`inicio_utc`/`fim_utc`), não verificado.
5. `src/hoje.md` ainda **não foi aberta no preview**; os nomes de colunas seguem o contrato acima,
   mas pode haver ajuste fino (ex.: `Inputs.table` com `format` que recebe `(value, i, data)`).
6. Ligar `guards.enforce` nos marts (passo 6b) e criar os marts `sources` e `status_vocab`.
